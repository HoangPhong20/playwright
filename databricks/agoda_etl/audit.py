"""Write one auditable status row per Databricks ETL layer and batch."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from pyspark.sql import SparkSession

from . import config


def write_audit(
    spark: SparkSession,
    manifest: dict,
    layer: str,
    status: str,
    input_records: int = 0,
    output_records: int = 0,
    quarantined_records: int = 0,
    error_message: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    row = spark.createDataFrame(
        [(
            manifest["batch_id"], manifest["airflow_dag_id"], manifest["airflow_run_id"],
            manifest["airflow_try_number"], layer, config.CONTRACT_VERSION, status,
            input_records, output_records, quarantined_records, error_message, now,
        )],
        "batch_id string, airflow_dag_id string, airflow_run_id string, airflow_try_number long, "
        "layer string, contract_version string, status string, input_records long, output_records long, "
        "quarantined_records long, error_message string, completed_at timestamp",
    )
    view = f"agoda_audit_{layer}_{uuid.uuid4().hex}"
    row.createOrReplaceTempView(view)
    spark.sql(
        f"""
        MERGE INTO {config.AUDIT_TABLE} AS target
        USING {view} AS source
        ON target.batch_id = source.batch_id AND target.layer = source.layer
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )
