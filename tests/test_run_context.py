from types import SimpleNamespace

import pytest

from agoda_crawler.run_context import RunContext, path_safe_identifier, run_context_from_args


def test_run_context_uses_airflow_identity_without_a_generated_id(tmp_path) -> None:
    context = RunContext(
        airflow_dag_id="agoda_daily_crawl",
        airflow_run_id="manual__2026-07-25T08:00:00+07:00",
        airflow_try_number=2,
    )

    output_dir = context.output_directory(tmp_path)

    assert context.batch_id == "agoda_daily_crawl__manual__2026-07-25T08:00:00+07:00"
    assert all(
        not path_part.startswith("run_")
        for path_part in output_dir.relative_to(tmp_path).parts
    )
    assert "%3A" in output_dir.as_posix()
    assert "%2B" in output_dir.as_posix()
    assert output_dir.parts[-1] == "attempt=2"
    assert context.completion_pointer_path(tmp_path).parent == context.batch_directory(tmp_path)
    assert context.completion_pointer_path(tmp_path).name == "completed_attempt.json"


def test_path_safe_identifier_handles_windows_unsafe_characters() -> None:
    assert path_safe_identifier("a/b:c+?") == "a%2Fb%3Ac%2B%3F"


def test_run_context_requires_explicit_airflow_identifiers() -> None:
    with pytest.raises(ValueError, match="required"):
        run_context_from_args(SimpleNamespace(airflow_dag_id=None, airflow_run_id=None))
