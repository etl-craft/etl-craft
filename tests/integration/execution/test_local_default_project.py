"""A local connector without project selection retains the mandatory-selection refusal."""

import yaml


def test_local_without_project_keeps_selection_refusal(cli_project):
    project = cli_project
    path = project.config.config_path
    raw = yaml.safe_load(path.read_text())
    raw["Orchestration"].pop("Project")
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    code, output = project.run("run", "--pipeline-code", "P")
    assert code == 2, output
    assert (
        "missing Orchestration.Project; supply --project P "
        "or set Orchestration.Project in this file"
    ) in output


def test_project_named_admin_commands_need_no_selection_of_their_own(cli_project):
    """Commands that name their project in the request bind it explicitly, as the demo does."""
    code, output = cli_project.run(
        "alert-channel", "set", "--project", "default", "--name", "oncall", "--kind", "EMAIL",
        "--recipients", "oncall@example.com", "--reason", "regression",
    )  # fmt: skip
    assert code == 0, output
    code, output = cli_project.run("alert-channel", "list", "--project", "default")
    assert code == 0 and "oncall" in output, output
