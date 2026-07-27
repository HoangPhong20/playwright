"""Stable schemas for business-only crawler JSONL files in the UC Volume."""

from pyspark.sql.types import StringType, StructField, StructType

from .config import BUSINESS_OUTPUT_COLUMNS


CRAWLER_OUTPUT_SCHEMA = StructType(
    [StructField(column, StringType(), True) for column in BUSINESS_OUTPUT_COLUMNS]
)
