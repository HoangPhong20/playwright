"""Exercise orchestration against a small stateful Delta merge boundary."""

from pathlib import Path, PurePosixPath
import re
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("pyspark")
sys.path.insert(0, str(Path(__file__).parents[1] / "databricks"))
from agoda_etl import bronze, config, gold, silver  # noqa: E402


class Predicate:
    def __init__(self, matches):
        self.matches = matches

    def __and__(self, other):
        return Predicate(lambda row: self.matches(row) and other.matches(row))


class Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return Predicate(lambda row: row[self.name] == value)

    def isin(self, values):
        return Predicate(lambda row: row[self.name] in values)


class Rows:
    def __init__(self, spark, rows):
        self.spark = spark
        self.rows = rows

    def where(self, predicate):
        return Rows(self.spark, [row for row in self.rows if predicate.matches(row)])

    def limit(self, count):
        return Rows(self.spark, self.rows[:count])

    def count(self):
        return len(self.rows)

    def createOrReplaceTempView(self, name):
        self.spark.views[name] = self.rows

    @property
    def write(self):
        return self

    def mode(self, mode):
        assert mode == "overwrite"
        return self

    def option(self, name, value):
        assert (name, value) == ("overwriteSchema", "true")
        return self

    def saveAsTable(self, table):
        self.spark.events.append(("overwrite", table))
        self.spark.fault(table, self.rows)
        self.spark.tables[table] = [dict(row) for row in self.rows]


class DeltaBoundary:
    """Only support the filters and MERGE statements emitted by these runners."""

    def __init__(self):
        self.tables = {table: [] for table in (
            config.BRONZE_TABLE, config.SILVER_TABLE, config.LEDGER_TABLE,
            config.AUDIT_TABLE, *config.GOLD_TABLES,
        )}
        self.views = {}
        self.events = []
        self.fault = lambda table, rows: None

    def table(self, table):
        return Rows(self, self.tables[table])

    def createDataFrame(self, rows, schema):
        names = [field.strip().split()[0] for field in schema.split(",")]
        return Rows(self, [dict(zip(names, row)) for row in rows])

    def sql(self, query):
        match = re.search(r"MERGE INTO (\S+) AS target\s+USING (\S+) AS source", query)
        assert match is not None, query
        table, view = match.groups()
        rows = self.views[view]
        keys = re.findall(r"target\.(\w+) = source\.\1", query)
        assert keys, query
        update = "WHEN MATCHED THEN UPDATE SET *" in query
        assert "WHEN NOT MATCHED THEN INSERT *" in query
        self.fault(table, rows)
        for row in rows:
            existing = next((item for item in self.tables[table]
                             if all(item[key] == row[key] for key in keys)), None)
            if existing is None:
                self.tables[table].append(dict(row))
            elif update:
                existing.update(row)
        self.events.append(("merge", table, [dict(row) for row in rows]))


@pytest.fixture
def pipeline(monkeypatch):
    spark = DeltaBoundary()
    location = PurePosixPath("/Volumes/agoda/raw/crawler/batch/run_manifest.json")
    files = [str(location.parent / name) for name in ("one.jsonl", "two.jsonl")]
    manifest = {
        "status": "complete", "batch_id": "batch", "airflow_dag_id": "dag",
        "airflow_run_id": "run", "airflow_try_number": 1,
        "stays": [{"output_file": "one.jsonl", "publishable_records": 1},
                  {"output_file": "two.jsonl", "publishable_records": 1}],
    }
    monkeypatch.setattr(bronze.runtime, "read_completed_manifest",
                        lambda *_: (manifest, location, files))
    monkeypatch.setattr(bronze.runtime, "require_tables", lambda *_: None)
    for module in (bronze, silver):
        monkeypatch.setattr(module, "F", SimpleNamespace(col=Column))
    reads = []

    def read_raw(_spark, file, *_):
        reads.append(file)
        return (Rows(spark, [{"record_id": file, "batch_id": "batch",
                              "source_file_path": file, "hotel_url": "same-hotel"}]),
                Rows(spark, []), 1, 0)

    monkeypatch.setattr(bronze.data_quality, "read_raw_records", read_raw)
    monkeypatch.setattr(bronze.data_quality, "upsert_quarantine", lambda *_: None)
    monkeypatch.setattr(silver.data_quality, "validate_silver_records",
                        lambda rows: (rows, Rows(spark, [])))
    monkeypatch.setattr(silver, "transform_bronze_to_silver", lambda rows: rows)
    return spark, files, reads, str(location)


def test_bronze_loaded_replay_skips_reads_and_writes(pipeline):
    spark, _, reads, path = pipeline
    bronze.run_bronze_ingestion(spark, path)
    before = list(spark.events)
    reads.clear()

    result = bronze.run_bronze_ingestion(spark, path)

    assert (result["files_loaded"], result["files_skipped"]) == (0, 2)
    assert reads == []
    assert spark.events == before
    assert len(spark.tables[config.BRONZE_TABLE]) == 2


@pytest.mark.parametrize("failed_file", [0, 1])
def test_bronze_resumes_after_merge_before_loaded_ledger(pipeline, failed_file):
    spark, files, reads, path = pipeline

    def fail_loaded(table, rows):
        if (table == config.LEDGER_TABLE and rows[0]["status"] == "loaded"
                and rows[0]["file_path"] == files[failed_file]):
            spark.fault = lambda *_: None
            raise RuntimeError("ledger unavailable after Bronze commit")

    spark.fault = fail_loaded
    with pytest.raises(RuntimeError, match="ledger unavailable"):
        bronze.run_bronze_ingestion(spark, path)
    assert len(spark.tables[config.BRONZE_TABLE]) == failed_file + 1
    assert [row["status"] for row in spark.tables[config.LEDGER_TABLE]] == (
        ["failed"] if failed_file == 0 else ["loaded", "failed"]
    )
    assert spark.tables[config.AUDIT_TABLE][0]["status"] == "failed"
    reads.clear()

    result = bronze.run_bronze_ingestion(spark, path)

    assert (result["files_loaded"], result["files_skipped"]) == (
        (2, 0) if failed_file == 0 else (1, 1)
    )
    assert reads == files[failed_file:]
    assert {row["record_id"] for row in spark.tables[config.BRONZE_TABLE]} == set(files)
    assert len(spark.tables[config.BRONZE_TABLE]) == 2
    assert all(row["status"] == "loaded" for row in spark.tables[config.LEDGER_TABLE])
    assert spark.tables[config.AUDIT_TABLE][0]["status"] == "success"


def test_silver_retry_retains_observation_history_and_record_ids(pipeline):
    spark, files, _, path = pipeline
    bronze.run_bronze_ingestion(spark, path)
    old = {"record_id": "old-observation", "batch_id": "older-batch",
           "source_file_path": files[0], "hotel_url": "same-hotel"}
    unrelated = {**old, "record_id": "undeclared-file", "batch_id": "batch",
                 "source_file_path": "not-in-manifest.jsonl"}
    spark.tables[config.BRONZE_TABLE].extend([old, unrelated])
    spark.tables[config.SILVER_TABLE].append(dict(old))

    def fail_success_audit(table, rows):
        if (table == config.AUDIT_TABLE and rows[0]["layer"] == "silver"
                and rows[0]["status"] == "success"):
            spark.fault = lambda *_: None
            raise RuntimeError("audit unavailable after Silver commit")

    spark.fault = fail_success_audit
    with pytest.raises(RuntimeError, match="audit unavailable"):
        silver.run_silver_transformation(spark, path)
    before = {row["record_id"] for row in spark.tables[config.SILVER_TABLE]}
    assert before == {"old-observation", *files}

    result = silver.run_silver_transformation(spark, path)
    silver.run_silver_transformation(spark, path)

    assert result["records_transformed"] == 2
    assert {row["record_id"] for row in spark.tables[config.SILVER_TABLE]} == before
    assert len(spark.tables[config.SILVER_TABLE]) == 3
    assert spark.tables[config.SILVER_TABLE][0] == old
    assert spark.tables[config.AUDIT_TABLE][-1]["status"] == "success"


def test_gold_middle_write_failure_marks_failed_and_rerun_publishes_all(pipeline, monkeypatch):
    spark, _, _, path = pipeline
    spark.tables[config.SILVER_TABLE] = [{"batch_id": "older"}, {"batch_id": "batch"}]
    for name in ("hotel_daily_summary", "destination_daily_summary",
                 "rating_distribution", "price_by_star"):
        def summary(history):
            assert history.rows == [{"batch_id": "older"}, {"batch_id": "batch"}]
            return Rows(spark, [{"published": "new"}])

        monkeypatch.setattr(gold, name, summary)
    for table in config.GOLD_TABLES:
        spark.tables[table] = [{"published": "old"}]

    def fail_second_write(table, rows):
        if table == config.DESTINATION_DAILY_SUMMARY:
            raise RuntimeError("second table failed")

    spark.fault = fail_second_write
    with pytest.raises(RuntimeError, match="second table failed"):
        gold.run_gold_aggregations(spark, path)

    assert spark.events[0][0:2] == ("merge", config.AUDIT_TABLE)
    assert spark.events[0][2][0]["status"] == "running"
    assert [event[1] for event in spark.events if event[0] == "overwrite"] == [
        config.HOTEL_DAILY_SUMMARY, config.DESTINATION_DAILY_SUMMARY,
    ]
    assert spark.tables[config.HOTEL_DAILY_SUMMARY] == [{"published": "new"}]
    assert spark.tables[config.PRICE_BY_STAR] == [{"published": "old"}]
    assert spark.tables[config.AUDIT_TABLE][0]["status"] == "failed"

    spark.events.clear()
    spark.fault = lambda *_: None
    result = gold.run_gold_aggregations(spark, path)

    assert result["tables_created"] == 4
    assert [event[1] for event in spark.events if event[0] == "overwrite"] == list(config.GOLD_TABLES)
    assert [event[2][0]["status"] for event in spark.events if event[0] == "merge"] == [
        "running", "success",
    ]
    assert all(spark.tables[table] == [{"published": "new"}] for table in config.GOLD_TABLES)
    assert spark.tables[config.AUDIT_TABLE][0]["output_records"] == 4
