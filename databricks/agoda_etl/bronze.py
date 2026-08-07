"""Manifest-driven, idempotent Bronze ingestion for Agoda JSONL files."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import uuid
from pathlib import PurePosixPath

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from . import audit, config, data_quality, runtime, utils


logger = logging.getLogger(__name__)


def _is_loaded(spark: SparkSession, batch_id: str, file_path: str) -> bool:
    return (
        spark.table(config.LEDGER_TABLE)
        .where((F.col("batch_id") == batch_id) & (F.col("file_path") == file_path))
        .where(F.col("status") == "loaded")
        .limit(1)
        .count()
        > 0
    )


def _upsert_ledger(
    spark: SparkSession,
    manifest: dict,
    manifest_path: PurePosixPath,
    file_path: str,
    status: str,
    row_count: int | None = None,
    error_message: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    update = spark.createDataFrame(
        [
            (
                manifest["batch_id"], file_path, str(manifest_path), config.BRONZE_TABLE, status, now,
                now if status == "loaded" else None, row_count, error_message,
            )
        ],
        "batch_id string, file_path string, manifest_path string, target_table string, status string, "
        "started_at timestamp, loaded_at timestamp, row_count long, error_message string",
    )
    view_name = f"agoda_ledger_update_{uuid.uuid4().hex}"
    update.createOrReplaceTempView(view_name)
    spark.sql(
        f"""
        MERGE INTO {config.LEDGER_TABLE} AS target
        USING {view_name} AS source
        ON target.batch_id = source.batch_id AND target.file_path = source.file_path
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )


def run_bronze_ingestion(spark: SparkSession, manifest_path: str) -> dict:
    """Load each manifest JSONL file exactly once into the Bronze Delta table."""
    manifest, location, source_files = runtime.read_completed_manifest(spark, manifest_path)
    runtime.require_tables(
        spark, config.BRONZE_TABLE, config.LEDGER_TABLE,
        config.QUARANTINE_TABLE, config.AUDIT_TABLE,
    )
    loaded_files = 0
    skipped_files = 0
    input_records = 0
    quarantined_records = 0
    staged_files: list[tuple[str, DataFrame, int, int, int]] = []
    try:
        expected_counts = utils.manifest_output_record_counts(manifest, location)
        for source_file in source_files:
            if _is_loaded(spark, manifest["batch_id"], source_file):
                skipped_files += 1
                continue
            valid, quarantined, file_input, file_invalid = data_quality.read_raw_records(
                spark, source_file, manifest, location
            )
            if file_input != expected_counts[source_file]:
                raise ValueError(
                    f"Manifest record count mismatch for {source_file}: "
                    f"expected={expected_counts[source_file]}, actual={file_input}"
                )
            data_quality.upsert_quarantine(spark, quarantined)
            staged_files.append((source_file, valid, file_input, file_invalid, valid.count()))
            input_records += file_input
            quarantined_records += file_invalid

        if input_records < 1:
            if skipped_files == len(source_files):
                result = {
                    "status": "success", "batch_id": manifest["batch_id"],
                    "airflow_dag_id": manifest["airflow_dag_id"],
                    "airflow_run_id": manifest["airflow_run_id"],
                    "airflow_try_number": manifest["airflow_try_number"],
                    "files_loaded": 0, "files_skipped": skipped_files,
                    "input_records": 0, "output_records": 0,
                    "quarantined_records": 0,
                }
                logger.info("Bronze ingestion already complete: %s", result)
                return result
            raise ValueError("No source records available for Bronze ingestion")
        if data_quality.exceeds_invalid_threshold(input_records, quarantined_records):
            raise ValueError(
                f"Data quality threshold exceeded: quarantined={quarantined_records}, "
                f"input={input_records}, max_ratio={config.MAX_INVALID_RATIO}, "
                f"max_records={config.MAX_INVALID_RECORDS}"
            )

        loaded_records = 0
        for source_file, staged, file_input, file_invalid, row_count in staged_files:
            if row_count < 1:
                continue
            try:
                _upsert_ledger(spark, manifest, location, source_file, "loading")
                stage_view_name = f"agoda_bronze_stage_{uuid.uuid4().hex}"
                staged.createOrReplaceTempView(stage_view_name)
                spark.sql(
                    f"""
                    MERGE INTO {config.BRONZE_TABLE} AS target
                    USING {stage_view_name} AS source
                    ON target.record_id = source.record_id
                    WHEN NOT MATCHED THEN INSERT *
                    """
                )
                _upsert_ledger(spark, manifest, location, source_file, "loaded", row_count=row_count)
                loaded_files += 1
                loaded_records += row_count
            except Exception as error:
                _upsert_ledger(spark, manifest, location, source_file, "failed", error_message=str(error)[:4000])
                raise
        if loaded_records < 1 and skipped_files == 0:
            raise ValueError("No valid records remain after data quality validation")
        result = {
            "status": "success", "batch_id": manifest["batch_id"],
            "airflow_dag_id": manifest["airflow_dag_id"],
            "airflow_run_id": manifest["airflow_run_id"],
            "airflow_try_number": manifest["airflow_try_number"],
            "files_loaded": loaded_files, "files_skipped": skipped_files,
            "input_records": input_records, "output_records": loaded_records,
            "quarantined_records": quarantined_records,
        }
        audit.write_audit(
            spark, manifest, "bronze", "success", input_records, loaded_records, quarantined_records
        )
        logger.info("Bronze ingestion complete: %s", result)
        return result
    except Exception as error:
        audit.write_audit(
            spark, manifest, "bronze", "failed", input_records, 0, quarantined_records,
            str(error)[:4000],
        )
        raise
