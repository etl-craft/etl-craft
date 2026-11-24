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
