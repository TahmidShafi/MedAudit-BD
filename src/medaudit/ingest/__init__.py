"""MedAudit BD dataset ingestion and schema validation module."""

from medaudit.ingest.models import BrandEntity, ProductRecord, SchemaValidationError
from medaudit.ingest.loader import (
    EXPECTED_COLUMNS,
    analyze_duplicate_combinations,
    load_dataset_records,
    validate_schema,
)

__all__ = [
    "EXPECTED_COLUMNS",
    "BrandEntity",
    "ProductRecord",
    "SchemaValidationError",
    "analyze_duplicate_combinations",
    "load_dataset_records",
    "validate_schema",
]
