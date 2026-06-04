"""Detail enrichment package public surface."""
from agoda_crawler.enrichment.detail import (
    DEFAULT_DETAIL_ENRICH_FIELDS,
    enrich_records_from_details,
    merge_missing_fields,
    needs_detail_enrichment,
    with_stay_params,
)

__all__ = [
    "DEFAULT_DETAIL_ENRICH_FIELDS",
    "enrich_records_from_details",
    "merge_missing_fields",
    "needs_detail_enrichment",
    "with_stay_params",
]
