import sys
from dataclasses import replace

import pytest

from etl_craft.core.conditions import Facts, Scope, parse
from etl_craft.core.enums import DependencyType, RunStatus
from etl_craft.core.errors import ConditionError, ExitCode, GraphError
from etl_craft.core.graph import (
    CycleError,
    SelfDependencyError,
    TaskEdge,
    TaskNode,
    TaskRunState,
    UnknownTaskError,
)
from etl_craft.core.graph import (
    build_graph as assemble_graph,
)

pytestmark = pytest.mark.unit


def nodes(*ids: int) -> list[TaskNode]:
    return [TaskNode(task_id=i) for i in ids]


FACTS = {"SUCCESS": "SUCCESS", "FAILURE": "FAILED", "ALWAYS": "FINISHED", "HAS_DATA": "HAS_DATA"}


def edge(task_id, depends_on_task_id, dependency_type="SUCCESS"):
    return TaskEdge(task_id, depends_on_task_id), FACTS[dependency_type]


def build_graph(tasks, edges):
    prepared = []
    for task in tasks:
        upstream = {
            (f"t{link.depends_on_task_id}",): link.depends_on_task_id
            for link, _ in edges
            if link.task_id == task.task_id
        }
        expression = " AND ".join(
            f"t{link.depends_on_task_id}.{fact}"
            for link, fact in edges
            if link.task_id == task.task_id
        )
        condition = task.condition or (parse(expression, Scope.TASK) if expression else None)
        prepared.append(replace(task, condition=condition, upstream=upstream))
    return assemble_graph(prepared, [link for link, _ in edges])


def conditional(task_id, expression, **kwargs):
    return TaskNode(task_id, condition=parse(expression, Scope.TASK), **kwargs)


def test_no_dependencies_is_a_single_wave():
    graph = build_graph(nodes(1, 2, 3), [])
    assert graph.waves() == [[1, 2, 3]]


def test_linear_chain_waves():
    # 1 -> 2 -> 3  (2 depends on 1, 3 depends on 2)
    graph = build_graph(nodes(1, 2, 3), [edge(2, 1), edge(3, 2)])
    assert graph.waves() == [[1], [2], [3]]


def test_diamond_shape_waves():
    #     1
    #    / \
    #   2   3
    #    \ /
    #     4
    graph = build_graph(nodes(1, 2, 3, 4), [edge(2, 1), edge(3, 1), edge(4, 2), edge(4, 3)])
    assert graph.waves() == [[1], [2, 3], [4]]


def test_self_dependency_rejected():
    with pytest.raises(SelfDependencyError):
        build_graph(nodes(1), [edge(1, 1)])


def test_direct_cycle_rejected():
    with pytest.raises(CycleError):
        build_graph(nodes(1, 2), [edge(1, 2), edge(2, 1)])


def test_indirect_cycle_rejected():
    with pytest.raises(CycleError):
        build_graph(nodes(1, 2, 3), [edge(1, 2), edge(2, 3), edge(3, 1)])


def test_unknown_task_id_in_edge_rejected():
    with pytest.raises(UnknownTaskError):
        build_graph(nodes(1, 2), [edge(1, 99)])


def test_unknown_fact_rejected():
    with pytest.raises(ConditionError, match="position"):
        parse("upstream.BOGUS", Scope.TASK)


def test_ready_with_no_edges_all_unstarted_tasks_ready():
    graph = build_graph(nodes(1, 2), [])
    assert graph.ready({}) == [1, 2]


def test_ready_excludes_terminal_tasks():
    graph = build_graph(nodes(1, 2), [])
    state = {1: TaskRunState(status="SUCCESS")}
    assert graph.ready(state) == [2]


def test_ready_success_edge_blocks_until_upstream_succeeds():
    # task 1 has no deps of its own, so its own retry-eligibility (tested
    # separately) is irrelevant here — only whether 2's edge is satisfied.
    graph = build_graph(nodes(1, 2), [edge(2, 1)])
    assert 2 not in graph.ready({})
    assert 2 not in graph.ready({1: TaskRunState(status="IN-PROGRESS")})
    assert 2 not in graph.ready({1: TaskRunState(status="FAILED")})
    assert graph.ready({1: TaskRunState(status="SUCCESS")}) == [2]


def test_ready_failure_edge_only_satisfied_by_failed_upstream():
    graph = build_graph(nodes(1, 2), [edge(2, 1, dependency_type="FAILURE")])
    assert 2 not in graph.ready({1: TaskRunState(status="SUCCESS")})
    assert 2 in graph.ready({1: TaskRunState(status="FAILED")}, failures_final=True)


@pytest.mark.parametrize("upstream_status", ["SUCCESS", "FAILED", "SKIPPED"])
def test_ready_always_edge_satisfied_by_any_terminal_status(upstream_status):
    graph = build_graph(nodes(1, 2), [edge(2, 1, dependency_type="ALWAYS")])
    assert 2 in graph.ready({1: TaskRunState(status=upstream_status)}, failures_final=True)


def test_ready_always_edge_not_satisfied_while_upstream_in_progress():
    graph = build_graph(nodes(1, 2), [edge(2, 1, dependency_type="ALWAYS")])
    assert 2 not in graph.ready({1: TaskRunState(status="IN-PROGRESS")})


def test_ready_has_data_edge_requires_success_and_positive_target_count():
    graph = build_graph(nodes(1, 2), [edge(2, 1, dependency_type="HAS_DATA")])
    assert 2 not in graph.ready({1: TaskRunState(status="SUCCESS", target_count=0)})
    assert 2 not in graph.ready({1: TaskRunState(status="SUCCESS", target_count=None)})
    assert graph.ready({1: TaskRunState(status="SUCCESS", target_count=5)}) == [2]
    assert 2 not in graph.ready({1: TaskRunState(status="FAILED", target_count=5)})


def test_has_data_reads_the_rows_written_before_the_target_count():
    graph = build_graph(nodes(1, 2), [edge(2, 1, dependency_type="HAS_DATA")])
    full_but_unchanged = TaskRunState(status="SUCCESS", target_count=5, rows_written=0)
    assert 2 not in graph.ready({1: full_but_unchanged})
    assert graph.ready({1: TaskRunState("SUCCESS", target_count=0, rows_written=3)}) == [2]


def test_ready_task_with_multiple_edges_needs_all_satisfied():
    graph = build_graph(nodes(1, 2, 3), [edge(3, 1), edge(3, 2)])
    # task 1 already SUCCESS (terminal, excluded); task 2 has no deps of its
    # own, so it's ready; task 3 still waits on task 2.
    assert graph.ready({1: TaskRunState(status="SUCCESS")}) == [2]
    assert graph.ready({1: TaskRunState(status="SUCCESS"), 2: TaskRunState(status="SUCCESS")}) == [
        3
    ]


def test_ready_reattempts_failed_task_itself():
    graph = build_graph(nodes(1), [])
    assert graph.ready({1: TaskRunState(status="FAILED")}) == [1]


def test_ready_excludes_in_progress_task_itself():
    graph = build_graph(nodes(1), [])
    assert graph.ready({1: TaskRunState(status="IN-PROGRESS")}) == []


def test_skipped_upstream_never_satisfies_success_edge():
    graph = build_graph(nodes(1, 2), [edge(2, 1)])
    assert graph.ready({1: TaskRunState(status="SKIPPED")}) == []


def test_build_graph_rejects_duplicate_task_ids():
    with pytest.raises(GraphError):
        build_graph(nodes(1, 1), [])


def test_build_graph_rejects_edge_with_unknown_task_id():
    # Distinct from test_unknown_task_id_in_edge_rejected: that one has an
    # unknown depends_on_task_id with a valid task_id; this is the other
    # side — task_id itself doesn't exist in the supplied task set.
    with pytest.raises(UnknownTaskError):
        build_graph(nodes(1, 2), [edge(99, 1)])


@pytest.mark.parametrize(
    ("expression", "one", "two"),
    [
        ("t1.SUCCESS AND t2.SUCCESS", None, True),
        ("t1.SUCCESS OR t2.SUCCESS", True, True),
        ("AT_LEAST(2, t1.SUCCESS, t2.SUCCESS, t3.SUCCESS)", None, True),
    ],
)
def test_condition_controls_readiness_and_admission(expression, one, two):
    graph = build_graph(
        [*nodes(1, 2, 3), conditional(4, expression)], [edge(4, i) for i in (1, 2, 3)]
    )
    first = {1: TaskRunState(status="SUCCESS")}
    second = {**first, 2: TaskRunState(status="SUCCESS")}
    assert graph.admission(4, first, {2}) is one
    assert (4 in graph.ready(first)) is (one is True)
    assert graph.evaluate(4, second) is two
    assert 4 in graph.ready(second)


@pytest.mark.parametrize(
    "expression",
    [
        "AT_LEAST(3, t1.SUCCESS, t2.SUCCESS)",
        "AT_LEAST(0, t1.SUCCESS, t2.SUCCESS)",
        "AT_LEAST(1, t1.SUCCESS)",
        "t1.STATUS",
        "t1.REJECTED = FAILED",
    ],
)
def test_malformed_conditions_are_refused(expression):
    with pytest.raises(ConditionError, match="position"):
        parse(expression, Scope.TASK)


@pytest.mark.parametrize("operator", ["AND", "OR"])
def test_cross_pipeline_conditions_use_bound_facts(operator):
    node = conditional(
        2, f"t1.SUCCESS {operator} other.load.SUCCESS", cross={("other", "load"): 10}
    )
    graph = build_graph([TaskNode(1), node], [edge(2, 1)])
    state = {1: TaskRunState(status="SUCCESS")}
    assert graph.ready({}) == [1]
    assert graph.ready({1: TaskRunState(status="IN-PROGRESS")}) == []
    assert 2 in graph.ready(state)
    assert (2 in graph.ready(state, {2: {10: Facts("FAILED")}})) is (operator == "OR")
    assert 2 in graph.ready(state, {2: {10: Facts("SUCCESS")}})
    assert graph.unsatisfiable({1: TaskRunState(status="SKIPPED")}) == (
        [2] if operator == "AND" else []
    )
    assert (2 in graph.ready({1: TaskRunState(status="FAILED")}, failures_final=True)) is (
        operator == "OR"
    )


# unsatisfiable(): never-run tasks that can never become ready under this run


def test_unsatisfiable_flags_a_failure_edge_whose_upstream_succeeded():
    # A failure watcher, on a run where nothing failed.
    graph = build_graph(nodes(1, 2), [edge(2, 1, dependency_type="FAILURE")])
    assert graph.unsatisfiable({1: TaskRunState(status="SUCCESS")}) == [2]


def test_unsatisfiable_ignores_an_upstream_that_merely_failed():
    # FAILED stays retry-eligible — "retry resumes" — so a SUCCESS edge on it
    # is "not yet", not "never". Converting this into a skip would report a
    # broken run as SUCCESS.
    graph = build_graph(nodes(1, 2), [edge(2, 1)])
    assert graph.unsatisfiable({1: TaskRunState(status="FAILED")}) == []


def test_unsatisfiable_treats_a_failure_as_final_when_no_retry_will_come():
    # A local run with nothing left to start: its failures stand, so what needs them to
    # succeed is doomed, transitively, and an ALWAYS dependent (an alert) may then run.
    graph = build_graph(nodes(1, 2, 3, 4), [edge(2, 1), edge(3, 2), edge(4, 3, "ALWAYS")])
    failed = {1: TaskRunState(status="FAILED")}
    assert graph.unsatisfiable(failed) == []
    assert graph.unsatisfiable(failed, failures_final=True) == [2, 3]
    skipped = {**failed, 2: TaskRunState(status="SKIPPED"), 3: TaskRunState(status="SKIPPED")}
    # The failed task stays eligible for another attempt; the run loop does not repeat it.
    assert graph.ready(skipped) == [1, 4]


def test_unsatisfiable_ignores_an_upstream_still_in_progress():
    graph = build_graph(nodes(1, 2), [edge(2, 1)])
    assert graph.unsatisfiable({1: TaskRunState(status="IN-PROGRESS")}) == []


def test_unsatisfiable_flags_a_has_data_edge_whose_upstream_wrote_nothing():
    graph = build_graph(nodes(1, 2), [edge(2, 1, dependency_type="HAS_DATA")])
    state = {1: TaskRunState(status="SUCCESS", target_count=0)}
    assert graph.unsatisfiable(state) == [2]


def test_unsatisfiable_cascades_to_a_fixpoint():
    # 1 SUCCESS -> 2 (FAILURE) can never run -> 3 (SUCCESS on 2) can never
    # run either, once 2 is settled SKIPPED. One pass would only find 2.
    graph = build_graph(nodes(1, 2, 3), [edge(2, 1, dependency_type="FAILURE"), edge(3, 2)])
    assert graph.unsatisfiable({1: TaskRunState(status="SUCCESS")}) == [2, 3]


def test_unsatisfiable_does_not_cascade_through_an_always_edge():
    # An ALWAYS edge is satisfied by the SKIPPED that 2 is about to get, so 3
    # is genuinely still runnable — the cascade must not over-reach.
    graph = build_graph(
        nodes(1, 2, 3),
        [edge(2, 1, dependency_type="FAILURE"), edge(3, 2, dependency_type="ALWAYS")],
    )
    assert graph.unsatisfiable({1: TaskRunState(status="SUCCESS")}) == [2]


def test_unsatisfiable_under_any_needs_every_edge_to_be_hopeless():
    tasks = [TaskNode(task_id=1), TaskNode(task_id=2), conditional(3, "t1.FAILED OR t2.FAILED")]
    graph = build_graph(
        tasks,
        [edge(3, 1, dependency_type="FAILURE"), edge(3, 2, dependency_type="FAILURE")],
    )
    # One upstream succeeded (that edge is hopeless), the other hasn't run.
    assert graph.unsatisfiable({1: TaskRunState(status="SUCCESS")}) == []
    assert graph.unsatisfiable(
        {1: TaskRunState(status="SUCCESS"), 2: TaskRunState(status="SUCCESS")}
    ) == [3]


def test_unsatisfiable_leaves_tasks_that_already_have_a_row_alone():
    # Only never-run tasks are reported. A task that already ran owns its own
    # status, whatever it is.
    graph = build_graph(nodes(1, 2), [edge(2, 1, dependency_type="FAILURE")])
    state = {1: TaskRunState(status="SUCCESS"), 2: TaskRunState(status="FAILED")}
    assert graph.unsatisfiable(state) == []


def test_check_acyclic_handles_a_chain_deeper_than_the_recursion_limit():
    # A deep chain is a configuration, not an engine bug: it must not hit RecursionError.
    depth = sys.getrecursionlimit() + 500
    ids = list(range(1, depth + 1))
    chain = [edge(i + 1, i) for i in range(1, depth)]
    graph = build_graph(nodes(*ids), chain)
    assert len(graph.waves()) == depth


def test_check_acyclic_skips_a_root_already_visited_as_a_descendant():
    # Task ids carry no ordering guarantee relative to the dependency
    # direction — 1 depending on 2 is perfectly ordinary. Walking roots in id
    # order then reaches 2 as a descendant of 1 first, so the outer loop must
    # skip it rather than restart the traversal.
    graph = build_graph(nodes(1, 2), [edge(1, 2)])
    assert graph.waves() == [[2], [1]]


def test_check_acyclic_still_finds_a_cycle_at_depth():
    depth = 2000
    ids = list(range(1, depth + 1))
    chain = [edge(i + 1, i) for i in range(1, depth)]
    chain.append(edge(1, depth))
    with pytest.raises(CycleError):
        build_graph(nodes(*ids), chain)


def test_each_graph_error_has_its_own_exit_code():
    codes = {
        error.exit_code for error in (GraphError, CycleError, SelfDependencyError, UnknownTaskError)
    }
    assert codes == {
        ExitCode.GRAPH,
        ExitCode.DEPENDENCY_CYCLE,
        ExitCode.SELF_DEPENDENCY,
        ExitCode.UNKNOWN_TASK,
    }


def test_a_cycle_error_names_the_cycle():
    with pytest.raises(CycleError, match=r"dependency cycle: 1 -> 2 -> 3 -> 1") as error:
        build_graph(nodes(1, 2, 3), [edge(1, 2), edge(2, 3), edge(3, 1)])
    assert error.value.cycle == (1, 2, 3, 1)


def test_enum_members_and_raw_strings_are_interchangeable():
    tasks = [TaskNode(task_id=1), conditional(2, "t1.HAS_DATA")]
    edges = [edge(2, 1, dependency_type=DependencyType.HAS_DATA)]
    graph = build_graph(tasks, edges)
    assert graph.ready({1: TaskRunState(status=RunStatus.SUCCESS, target_count=1)}) == [2]
    assert graph.ready({1: TaskRunState(status="SUCCESS", target_count=1)}) == [2]


def test_dependencies_of_returns_a_copy():
    graph = build_graph(nodes(1, 2), [edge(2, 1)])
    graph.dependencies_of(2).clear()
    assert graph.dependencies_of(2) == [edge(2, 1)[0]]
    assert graph.task_ids == (1, 2)


def test_blank_condition_with_no_dependencies_is_ready():
    graph = build_graph([TaskNode(task_id=1)], [])
    assert graph.evaluate(1, {}) is True
    assert graph.ready({}) == [1]
    assert graph.unsatisfiable({}) == []
