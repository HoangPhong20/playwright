"""Gold metrics rebuilt from the complete Agoda Silver history."""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from . import audit, config, runtime


def hotel_daily_summary(silver: DataFrame) -> DataFrame:
    return silver.groupBy("check_in_date", "destination", "hotel_url", "hotel_name").agg(
        F.min("price_amount").alias("min_price_amount"),
        F.avg("price_amount").cast("decimal(18,0)").alias("avg_price_amount"),
        F.max("price_amount").alias("max_price_amount"),
        F.max("rating").alias("rating"),
        F.max("review_count").alias("review_count"),
        F.max("star_rating").alias("star_rating"),
        F.count("*").alias("observations"),
        F.max("crawled_at").alias("last_crawled_at"),
    )


def destination_daily_summary(silver: DataFrame) -> DataFrame:
    return silver.groupBy("check_in_date", "destination").agg(
        F.countDistinct("hotel_url").alias("hotel_count"),
        F.avg("price_amount").cast("decimal(18,0)").alias("avg_price_amount"),
        F.min("price_amount").alias("min_price_amount"),
        F.max("price_amount").alias("max_price_amount"),
        F.avg("rating").cast("decimal(3,1)").alias("avg_rating"),
        F.count("*").alias("observations"),
    )


def rating_distribution(silver: DataFrame) -> DataFrame:
    bucket = (
        F.when(F.col("rating") >= 9, "Excellent (9.0+)")
        .when(F.col("rating") >= 8, "Very Good (8.0-8.9)")
        .when(F.col("rating") >= 7, "Good (7.0-7.9)")
        .when(F.col("rating") >= 6, "Satisfactory (6.0-6.9)")
        .otherwise("Below Average (<6.0)")
    )
    return (
        silver.filter(F.col("rating").isNotNull())
        .withColumn("rating_bucket", bucket)
        .groupBy("check_in_date", "destination", "rating_bucket")
        .agg(
            F.count("*").alias("observations"),
            F.avg("price_amount").cast("decimal(18,0)").alias("avg_price_amount"),
        )
    )


def price_by_star(silver: DataFrame) -> DataFrame:
    return (
        silver.filter(F.col("star_rating").isNotNull())
        .groupBy("check_in_date", "destination", "star_rating")
        .agg(
            F.count("*").alias("observations"),
            F.avg("price_amount").cast("decimal(18,0)").alias("avg_price_amount"),
            F.expr("percentile_approx(price_amount, 0.5)").cast("decimal(18,0)").alias("median_price_amount"),
            F.avg("rating").cast("decimal(3,1)").alias("avg_rating"),
        )
    )


def _overwrite_table(df: DataFrame, table: str) -> int:
    count = df.count()
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)
    return count


def run_gold_aggregations(spark: SparkSession, manifest_path: str) -> dict:
    """Rebuild Gold tables from all Silver history after validating this batch."""
    manifest, _, _ = runtime.read_completed_manifest(spark, manifest_path)
    runtime.require_tables(spark, config.SILVER_TABLE, config.AUDIT_TABLE, *config.GOLD_TABLES)
    input_records = 0
    try:
        silver = spark.table(config.SILVER_TABLE)
        input_records = silver.count()
        if input_records == 0:
            raise ValueError("Silver history is empty; run Silver transformation first")

        table_stats = {
            config.HOTEL_DAILY_SUMMARY: _overwrite_table(hotel_daily_summary(silver), config.HOTEL_DAILY_SUMMARY),
            config.DESTINATION_DAILY_SUMMARY: _overwrite_table(destination_daily_summary(silver), config.DESTINATION_DAILY_SUMMARY),
            config.RATING_DISTRIBUTION: _overwrite_table(rating_distribution(silver), config.RATING_DISTRIBUTION),
            config.PRICE_BY_STAR: _overwrite_table(price_by_star(silver), config.PRICE_BY_STAR),
        }
        output_records = sum(table_stats.values())
        audit.write_audit(spark, manifest, "gold", "success", input_records, output_records)
        return {
            "status": "success", "batch_id": manifest["batch_id"],
            "tables_created": len(table_stats), "table_stats": table_stats,
        }
    except Exception as error:
        audit.write_audit(spark, manifest, "gold", "failed", input_records, error_message=str(error)[:4000])
        raise
