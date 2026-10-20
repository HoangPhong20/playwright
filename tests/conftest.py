import importlib.util
import os
from pathlib import Path
import pytest
import sys


@pytest.fixture
def representative_job_manifest_fields() -> dict:
    """Return the shared valid per-job data used by local and ETL tests."""
    return {
        "destinations": ["Vung Tau"],
        "planned_stays": [
            {"check_in": "2026-08-15", "check_out": "2026-08-16"}
        ],
        "jobs": [
            {
                "destination": "Vung Tau",
                "check_in": "2026-08-15",
                "check_out": "2026-08-16",
                "pages_requested": 5,
                "pages_collected": 1,
                "status": "complete",
                "stop_reason": "end_of_results",
                "page_statuses": {"1": "collected"},
            }
        ],
    }


@pytest.fixture(scope="session")
def spark_session(tmp_path_factory):
    """Start one bounded local Spark session for optional ETL behavior tests."""
    pytest.importorskip("pyspark", reason="local Spark behavior tests require PySpark")
    pyspark_spec = importlib.util.find_spec("pyspark")
    assert pyspark_spec is not None and pyspark_spec.origin is not None

    spark_environment = {
        "SPARK_HOME": str(Path(pyspark_spec.origin).parent),
        "PYSPARK_PYTHON": str(Path(sys.executable).resolve()),
        "PYSPARK_DRIVER_PYTHON": str(Path(sys.executable).resolve()),
        "SPARK_LOCAL_IP": "127.0.0.1",
    }
    java_21 = Path("C:/Program Files/Java/jdk-21")
    if os.name == "nt" and java_21.is_dir():
        spark_environment["JAVA_HOME"] = str(java_21)
    old_environment = {name: os.environ.get(name) for name in spark_environment}
    os.environ.update(spark_environment)

    from pyspark.sql import SparkSession

    warehouse_dir = tmp_path_factory.mktemp("spark-warehouse")
    local_dir = tmp_path_factory.mktemp("spark-local")
    spark = None
    try:
        spark = (
            SparkSession.builder.master("local[2]")
            .appName("agoda-etl-tests")
            .config("spark.ui.enabled", "false")
            .config("spark.default.parallelism", "2")
            .config("spark.sql.shuffle.partitions", "2")
            .config("spark.sql.adaptive.enabled", "false")
            .config("spark.driver.host", "127.0.0.1")
            .config("spark.driver.bindAddress", "127.0.0.1")
            .config("spark.sql.warehouse.dir", warehouse_dir.as_uri())
            .config("spark.local.dir", str(local_dir))
            .getOrCreate()
        )
        spark.sparkContext.setLogLevel("ERROR")
        yield spark
    finally:
        if spark is not None:
            spark.stop()
        for name, value in old_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
