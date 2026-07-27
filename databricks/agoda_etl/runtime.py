"""Spark-specific runtime helpers shared by Databricks ETL layers."""

from __future__ import annotations

from pathlib import PurePosixPath

from pyspark.sql import SparkSession

from . import config, utils


def read_completed_manifest(
    spark: SparkSession, manifest_path: str
) -> tuple[dict, PurePosixPath, list[str]]:
    """Read and validate one completed manifest from the configured UC Volume."""
    location = utils.validate_manifest_path(manifest_path, config.VOLUME_ROOT)
    rows = spark.read.option("wholetext", True).text(str(location)).limit(1).collect()
    if not rows:
        raise FileNotFoundError(f"Manifest does not exist: {location}")
    manifest = utils.parse_manifest_text(rows[0]["value"])
    return manifest, location, utils.manifest_output_files(manifest, location)


def require_tables(spark: SparkSession, *table_names: str) -> None:
    """Fail early when the one-time Unity Catalog setup has not been run."""
    missing = [table for table in table_names if not spark.catalog.tableExists(table)]
    if missing:
        formatted = ", ".join(missing)
        raise RuntimeError(
            f"Missing required Unity Catalog table(s): {formatted}. "
            "Run setup_uc_objects_wrapper once before the daily ETL Job."
        )
