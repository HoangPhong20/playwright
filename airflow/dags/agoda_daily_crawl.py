"""Daily Airflow DAG for the Agoda Playwright crawler."""

from __future__ import annotations

from datetime import datetime, timedelta
import os

import pendulum
from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.bash import BashOperator


def _env_value(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    value = int(_env_value(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


LOCAL_TIMEZONE = pendulum.timezone(
    _env_value("AGODA_AIRFLOW_TIMEZONE", "Asia/Ho_Chi_Minh")
)
RUN_OUTPUT_ROOT = _env_value("AGODA_AIRFLOW_OUTPUT_DIR", "data/airflow")
CHECK_IN_OFFSET_DAYS = _env_int("AGODA_CHECK_IN_OFFSET_DAYS", 21)
DAG_SCHEDULE = _env_value("AGODA_AIRFLOW_SCHEDULE", "0 8 * * *")
TASK_RETRIES = _env_int("AGODA_AIRFLOW_RETRIES", 1)
RETRY_DELAY_MINUTES = _env_int("AGODA_AIRFLOW_RETRY_DELAY_MINUTES", 5, minimum=1)
LOCAL_RETENTION_DAYS = _env_int("AGODA_LOCAL_RETENTION_DAYS", 14, minimum=1)

with DAG(
    dag_id="agoda_daily_crawl",
    description="Crawl one check-in date 21 days after each daily Airflow interval.",
    start_date=datetime(2026, 1, 1, tzinfo=LOCAL_TIMEZONE),
    schedule=DAG_SCHEDULE,
    catchup=False,
    max_active_runs=1,
    params={
        "check_in_offset_days": Param(
            CHECK_IN_OFFSET_DAYS,
            type="integer",
            minimum=0,
            description="Days after the Airflow data interval end to use as check-in.",
        ),
    },
    default_args={
        "owner": "data-engineering",
        "retries": TASK_RETRIES,
        "retry_delay": timedelta(minutes=RETRY_DELAY_MINUTES),
    },
    tags=["agoda", "playwright", "daily"],
) as dag:
    crawl_agoda = BashOperator(
        task_id="crawl_agoda",
        bash_command=(
            'python main.py --date "$CRAWL_DATE" '
            f'--output-dir "{RUN_OUTPUT_ROOT}" '
            '--airflow-dag-id "{{ dag.dag_id }}" '
            '--airflow-run-id "{{ run_id }}" '
            '--airflow-try-number "{{ ti.try_number }}"'
        ),
        env={
            "CRAWL_DATE": "{{ macros.ds_add(data_interval_end | ds, params.check_in_offset_days) }}",
        },
        append_env=True,
        cwd="/opt/airflow/app",
    )

    verify_output = BashOperator(
        task_id="verify_output",
        bash_command=(
            "python airflow/scripts/validate_latest_run.py "
            f'--output-dir "{RUN_OUTPUT_ROOT}" '
            '--airflow-dag-id "{{ dag.dag_id }}" '
            '--airflow-run-id "{{ run_id }}"'
        ),
        cwd="/opt/airflow/app",
    )

    upload_to_uc_volume = BashOperator(
        task_id="upload_to_uc_volume",
        bash_command=(
            "python airflow/scripts/upload_to_uc_volume.py "
            f'--output-dir "{RUN_OUTPUT_ROOT}" '
            '--airflow-dag-id "{{ dag.dag_id }}" '
            '--airflow-run-id "{{ run_id }}"'
        ),
        cwd="/opt/airflow/app",
    )

    cleanup_local_output = BashOperator(
        task_id="cleanup_local_output",
        bash_command=(
            "python airflow/scripts/cleanup_local_output.py "
            f'--output-dir "{RUN_OUTPUT_ROOT}" --debug-dir "debug" '
            f'--retention-days {LOCAL_RETENTION_DAYS} '
            '--airflow-dag-id "{{ dag.dag_id }}" '
            '--airflow-run-id "{{ run_id }}"'
        ),
        cwd="/opt/airflow/app",
    )

    crawl_agoda >> verify_output >> upload_to_uc_volume >> cleanup_local_output
