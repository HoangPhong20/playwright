import ast
import os
from pathlib import Path


def test_dag_uses_a_daily_schedule_and_interval_based_check_in() -> None:
    source = (
        Path(__file__).parents[1] / "airflow" / "dags" / "agoda_daily_crawl.py"
    ).read_text(encoding="utf-8")

    assert '"AGODA_AIRFLOW_SCHEDULE"' in source
    assert '"AGODA_CHECK_IN_OFFSET_DAYS"' in source
    assert '"AGODA_LOCAL_RETENTION_DAYS"' in source
    assert '--date "$CRAWL_DATE"' in source
    assert "date-start" not in source
    assert "date-end" not in source
    assert "data_interval_end | ds" in source
    assert "params.check_in_offset_days" in source
    assert "agoda_check_in" not in source
    assert "agoda_check_out" not in source
    assert "upload_to_uc_volume" in source
    assert "trigger_databricks_job" in source
    assert "cleanup_local_output" in source
    assert "crawl_agoda >> verify_output >> upload_to_uc_volume >> trigger_databricks_job >> cleanup_local_output" in source


def test_dag_schedule_fallback_is_0415_when_env_is_absent_or_blank(monkeypatch) -> None:
    path = Path(__file__).parents[1] / "airflow" / "dags" / "agoda_daily_crawl.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    env_function = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_env_value"
    )
    schedule_assignment = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "DAG_SCHEDULE" for target in node.targets)
    )
    code = compile(
        ast.fix_missing_locations(ast.Module(body=[env_function, schedule_assignment], type_ignores=[])),
        str(path),
        "exec",
    )

    for environment_value in (None, "   "):
        if environment_value is None:
            monkeypatch.delenv("AGODA_AIRFLOW_SCHEDULE", raising=False)
        else:
            monkeypatch.setenv("AGODA_AIRFLOW_SCHEDULE", environment_value)
        namespace = {"os": os}
        exec(code, namespace)
        assert namespace["DAG_SCHEDULE"] == "15 4 * * *"
