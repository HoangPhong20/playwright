"""Manual Airflow DAG for the Agoda Playwright crawler."""

from __future__ import annotations

from datetime import datetime, timedelta

import pendulum
from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator


LOCAL_TIMEZONE = pendulum.timezone("Asia/Ho_Chi_Minh")
RUN_OUTPUT_ROOT = "data/airflow"

with DAG(
    dag_id="agoda_daily_crawl",
    description="Run the Agoda crawler manually and verify its isolated output.",
    start_date=datetime(2026, 1, 1, tzinfo=LOCAL_TIMEZONE),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "data-engineering",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["agoda", "playwright", "local"],
) as dag:
    crawl_agoda = BashOperator(
        task_id="crawl_agoda",
        bash_command=(
            'python main.py --date-start "$CHECK_IN" --date-end "$CHECK_OUT" '
            f'--output-dir "{RUN_OUTPUT_ROOT}" '
            '--airflow-dag-id "{{ dag.dag_id }}" '
            '--airflow-run-id "{{ run_id }}" '
            '--airflow-try-number "{{ ti.try_number }}"'
        ),
        env={
            "CHECK_IN": "{{ var.value.agoda_check_in }}",
            "CHECK_OUT": "{{ var.value.agoda_check_out }}",
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
            '--airflow-run-id "{{ run_id }}" '
            '--airflow-try-number "{{ ti.try_number }}"'
        ),
        cwd="/opt/airflow/app",
    )

    crawl_agoda >> verify_output
