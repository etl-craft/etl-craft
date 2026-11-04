"""Resource discovery, deployment-profile sizing and role startup, from supplied measurements."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from etl_craft.config import load_config
from etl_craft.config.sizing import start_role
from etl_craft.core.enums import DeploymentProfile
from etl_craft.core.errors import ConfigurationError
from etl_craft.core.resources import GIB, MIB, Ceilings, Host, discover, size
from etl_craft.services.doctor import Status, resource_checks

pytestmark = pytest.mark.unit


def host(files=None, affinity=None, cpus=None, memory=None):
    files = files or {}
    return Host(files.get, lambda: affinity, cpus, memory)


def machine(cpus, memory):
    """A host whose only limits are its own CPU count and memory."""
    return host({"/proc/self/cgroup": "0::/\n"}, affinity=cpus, cpus=cpus, memory=memory)


def test_the_tightest_inherited_cgroup_v2_limit_applies_over_affinity_and_host():
    allocation = discover(
        host(
            {
                "/proc/self/cgroup": "0::/a/b\n",
                "/sys/fs/cgroup/a/b/cpu.max": "max 100000\n",
                "/sys/fs/cgroup/a/cpu.max": "150000 100000\n",
                "/sys/fs/cgroup/a/b/memory.max": "max\n",
                "/sys/fs/cgroup/a/memory.max": f"{512 * MIB}\n",
            },
            affinity=8,
            cpus=16,
            memory=64 * GIB,
        )
    )
    assert allocation.cpus.value == 1.5 and allocation.cpus.source == "/sys/fs/cgroup/a/cpu.max"
    assert allocation.memory.value == 512 * MIB
    assert allocation.memory.source == "/sys/fs/cgroup/a/memory.max"
    assert (allocation.host_cpus, allocation.scope) == (16, "/a/b")


def test_affinity_tighter_than_the_quota_applies():
    allocation = discover(
        host(
            {"/proc/self/cgroup": "0::/\n", "/sys/fs/cgroup/cpu.max": "400000 100000\n"},
            affinity=2,
            cpus=16,
            memory=8 * GIB,
        )
    )
    assert (allocation.cpus.value, allocation.cpus.source) == (2.0, "CPU affinity")
    assert allocation.memory.source == "host memory"


def test_cgroup_v1_quota_and_an_unlimited_memory_value_read_from_the_container_root():
    allocation = discover(
        host(
            {
                "/proc/self/cgroup": "4:cpu,cpuacct:/docker/x\n5:memory:/docker/x\n",
                "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "50000\n",
                "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000\n",
                "/sys/fs/cgroup/memory/memory.limit_in_bytes": "9223372036854771712\n",
            },
            cpus=4,
            memory=8 * GIB,
        )
    )
    assert allocation.cpus.value == 0.5
    assert (allocation.memory.value, allocation.memory.source) == (8 * GIB, "host memory")


def test_unreadable_measurements_are_unavailable_and_sizing_states_its_fallbacks():
    allocation = discover(host())
    assert allocation.cpus.value is None and allocation.memory.value is None
    assert "no affinity" in allocation.cpus.detail
    sizing = size(allocation, DeploymentProfile.CONTROLLER)
    assert "sized as one CPU" in sizing.fallbacks[0]
    assert "not limited by memory" in sizing.fallbacks[1]
    assert sizing.server_threads.value == 1
    assert sizing.reserve_memory is None


def test_a_malformed_cgroup_value_fails_with_the_file():
    broken = host({"/proc/self/cgroup": "0::/\n", "/sys/fs/cgroup/cpu.max": "lots 100000"})
    with pytest.raises(ConfigurationError, match=r"/sys/fs/cgroup/cpu.max: 'lots 100000'"):
        discover(broken)


def test_laptop_reserves_half_the_host_and_caps_server_threads():
    sizing = size(discover(machine(8, 16 * GIB)), DeploymentProfile.LAPTOP)
    assert (sizing.reserve_cpus, sizing.reserve_memory) == (4.0, 8 * GIB)
    assert sizing.task_slots.value == 14 and "CPU" in sizing.task_slots.reason
    assert sizing.python_slots.value == 3
    assert sizing.warehouse_slots.value == 14
    assert sizing.server_threads.value == 4
    assert sizing.engine_pool.value == 2 + 2 + 4


def test_server_uses_the_dedicated_host_and_workers_profile_runs_no_tasks():
    allocation = discover(machine(8, 16 * GIB))
    server = size(allocation, DeploymentProfile.CONTROLLER)
    assert server.task_slots.value == 26 and server.python_slots.value == 6
    assert server.server_threads.value == 32
    controller = size(allocation, DeploymentProfile.CONTROLLER_AGENTS)
    assert controller.task_slots.value == 0 and "runs no tasks" in controller.task_slots.reason


def test_memory_binds_when_it_is_tighter_than_cpu():
    sizing = size(discover(machine(16, 3 * GIB)), DeploymentProfile.CONTROLLER)
    # 3 GB less the 1 GB reserve and the 256 MB process leaves 1792 MB: 14 tasks of 128 MB.
    assert sizing.task_slots.value == 14 and sizing.task_slots.reason.startswith("memory")
    assert sizing.python_slots.value == 3


def test_written_settings_are_ceilings_never_requests():
    allocation = discover(machine(8, 16 * GIB))
    sizing = size(allocation, DeploymentProfile.CONTROLLER, Ceilings(4, 1, 2))
    assert (sizing.task_slots.value, sizing.python_slots.value) == (4, 1)
    assert sizing.warehouse_slots.value == 2
    assert sizing.task_slots.reason == "total task slots ceiling"
    roomy = size(allocation, DeploymentProfile.CONTROLLER, Ceilings(500))
    assert roomy.task_slots.value == 26


def write_config(tmp_path: Path, deployment: dict | None = None, **orchestration) -> Path:
    raw: dict = {
        "Secrets": {"Source_type": "ENVIRONMENT"},
        "Orchestration": {**orchestration},
    }
    if deployment is not None:
        raw["Deployment"] = deployment
    raw["Engine"] = {"dev": {"Jdbc_url": "jdbc:sqlite:engine.db", "Schema": "main"}}
    path = tmp_path / "craft-connector.yml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_no_profile_keeps_the_configuration_and_only_logs_the_measurement(tmp_path, caplog):
    config = load_config(write_config(tmp_path, Local_python_slots=3))
    caplog.set_level(logging.INFO, "etl_craft.config.sizing")
    assert start_role(config, server=True, host=machine(8, 16 * GIB)) is config
    assert "CPUs 8 CPUs from CPU affinity" in caplog.text


def test_a_profile_sizes_the_role_within_written_ceilings(tmp_path):
    path = write_config(tmp_path, {"Profile": "CONTROLLER"}, Local_python_slots=2)
    before = path.read_bytes()
    config = start_role(load_config(path), server=False, host=machine(8, 16 * GIB))
    assert config.sizing is not None and config.deployment == DeploymentProfile.CONTROLLER
    assert config.limits.max_parallel_tasks == 26
    assert config.limits.local_python_slots == 2
    assert path.read_bytes() == before
    capped = write_config(tmp_path, {"Profile": "CONTROLLER"}, Local_warehouse_slots=4)
    sized = start_role(load_config(capped), server=False, host=machine(8, 16 * GIB))
    assert sized.limits.local_warehouse_slots == 4


def test_controller_agents_reserves_no_local_execution_slots(tmp_path):
    config = load_config(write_config(tmp_path))
    from dataclasses import replace

    agents = replace(config, deployment=DeploymentProfile.CONTROLLER_AGENTS)
    sized = start_role(agents, server=True, host=machine(8, 16 * GIB))
    assert sized.limits.max_parallel_tasks == 0
    assert sized.limits.local_python_slots == 0
    assert sized.limits.local_warehouse_slots == 0


def test_an_allocation_too_small_for_a_slot_refuses_run_and_queues_on_the_server(tmp_path, caplog):
    config = load_config(write_config(tmp_path, {"Profile": "LAPTOP"}))
    small = machine(1, 4 * GIB)
    with pytest.raises(ConfigurationError, match=r"no task slot fits.*Raise the allocation"):
        start_role(config, server=False, host=small)
    served = start_role(config, server=True, host=small)
    assert served.limits.max_parallel_tasks == 0
    assert "starting with no task slots" in caplog.text
    tiny = machine(4, 200 * MIB)
    with pytest.raises(ConfigurationError, match=r"200 MB .*needs about 256 MB"):
        start_role(config, server=True, host=tiny)


@pytest.mark.parametrize(
    ("deployment", "extra", "message"),
    [
        ({"Profile": "cluster"}, {}, r"Deployment.Profile='cluster'; expected one of"),
        ({"Profile": "CONTROLLER_AGENTS"}, {}, "agents share one PostgreSQL Engine DB"),
        ({"Profile": "LAPTOP"}, {"Api_address": "0.0.0.0:8730"}, "binds to loopback"),
        ({"dev": {"Profile": "LAPTOP"}}, {}, r"unknown key\(s\) \['dev'\] in Deployment"),
    ],
)
def test_deployment_settings_are_validated(tmp_path, deployment, extra, message):
    with pytest.raises(ConfigurationError, match=message):
        load_config(write_config(tmp_path, deployment, **extra))


def test_doctor_reports_measurements_recommendation_and_sizes_without_a_profile(tmp_path):
    path = write_config(tmp_path)
    before = path.read_bytes()
    checks = {c.name: c for c in resource_checks(load_config(path), machine(8, 16 * GIB))}
    assert checks["Resources: CPU"].detail == "8 CPUs from CPU affinity (8 CPUs)"
    assert "Recommended: LAPTOP" in checks["Deployment profile"].detail
    assert checks["Sizing: task slots"].detail.startswith("14 (CPU")
    assert checks["Sizing: Engine DB pool"].detail == "10 (Orchestration.Db_pool_size)"
    blind = {c.name: c for c in resource_checks(load_config(path), host())}
    assert blind["Resources: memory"].status is Status.WARN
    assert "no automatic task-memory admission" in blind["Resources: memory"].detail
    assert path.read_bytes() == before


@pytest.mark.parametrize("profile", ["server", "server-workers"])
def test_removed_deployment_profiles_are_refused(tmp_path, profile):
    path = write_config(tmp_path, {"Profile": profile})
    with pytest.raises(
        ConfigurationError, match=r"Deployment.Profile=.*expected one of.*CONTROLLER"
    ):
        load_config(path)


def test_explicit_python_slots_can_exceed_estimate_with_agent_cpu_and_total_bounds():
    from etl_craft.core.resources import size_agent

    allocation = discover(machine(2, 256 * MIB))
    assert size_agent(allocation, Ceilings()).python_slots.value == 0
    explicit = size_agent(allocation, Ceilings(python_slots=1))
    assert explicit.profile == DeploymentProfile.CONTROLLER_AGENTS
    assert explicit.python_slots.value == explicit.task_slots.value == 1
    assert "set explicitly to 1" in explicit.python_slots.reason
    assert "estimate allowed 0" in explicit.python_slots.reason
    assert "512 MB each" in explicit.python_slots.reason
    cpu_limited = size_agent(discover(machine(1, 1024 * MIB)), Ceilings(python_slots=2))
    assert cpu_limited.python_slots.value == 0
    capped = size_agent(discover(machine(4, 2048 * MIB)), Ceilings(1, 3))
    assert capped.python_slots.value == capped.task_slots.value == 1


def test_explicit_python_slots_refuse_less_than_the_process_base_before_start():
    from etl_craft.core.resources import size_agent

    with pytest.raises(ConfigurationError) as caught:
        size_agent(discover(machine(4, 256 * MIB)), Ceilings(python_slots=2))
    for part in (
        "Local_python_slots/--python-slots=2",
        "usable memory 144 MB",
        "80 MB base cost",
        "lower",
        "raise",
    ):
        assert part in str(caught.value)


def test_doctor_and_startup_show_explicit_and_estimated_python_slots(tmp_path, caplog):
    path = write_config(tmp_path, {"Profile": "CONTROLLER"}, Local_python_slots=2)
    measured = machine(4, 2 * GIB)
    checks = {c.name: c for c in resource_checks(load_config(path), measured)}
    assert "set explicitly to 2" in checks["Sizing: python slots"].detail
    assert "estimate allowed 1" in checks["Sizing: python slots"].detail
    caplog.set_level(logging.INFO, "etl_craft.config.sizing")
    start_role(load_config(path), server=False, host=measured)
    assert "set explicitly to 2" in caplog.text
    assert "estimate allowed 1" in caplog.text
