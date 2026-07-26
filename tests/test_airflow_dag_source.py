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
    assert "cleanup_local_output" in source
    assert "crawl_agoda >> verify_output >> upload_to_uc_volume >> cleanup_local_output" in source
