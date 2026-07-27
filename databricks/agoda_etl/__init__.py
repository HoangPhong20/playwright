"""Manifest-driven Agoda ETL package for Databricks Jobs.

Import a layer directly, for example ``agoda_etl.bronze``.  Keeping this
initializer free of Spark imports lets configuration and pure helpers be used
without eagerly loading every ETL layer.
"""
