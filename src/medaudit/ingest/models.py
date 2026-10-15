"""Data models and exception definitions for the ingest module."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class SchemaValidationError(ValueError):
    """Raised when incoming dataset schema violates required column specifications."""
    pass


class BrandEntity(BaseModel):
    """Deduplicated brand-manufacturer entity.
    
    In the raw dataset, 13,934 distinct brand names exist, spanning 14,013
    (brand_name, manufacturer) combinations. brand_id is reserved for this
    deduplicated entity.
    """
    model_config = ConfigDict(frozen=True)

    brand_id: int = Field(description="Deterministic integer ID for the deduplicated brand entity")
    brand_name: str = Field(description="Display brand name")
    normalized_brand_name: str = Field(description="Trimmed, normalized brand name")
    manufacturer: str = Field(description="Manufacturing pharmaceutical company")


class ProductRecord(BaseModel):
    """Domain model for a single pharmaceutical SKU record.
    
    1:1 with the 21,714 rows in the raw dataset.
    The raw CSV's 'brand id' is explicitly mapped to product_id here.
    """
    model_config = ConfigDict(frozen=True)

    product_id: int = Field(description="Unique product SKU ID, mapped from raw 'brand id'")
    brand_id: int = Field(description="Foreign key referencing the deduplicated BrandEntity")
    raw_brand_name: str = Field(description="Raw brand name from dataset")
    normalized_brand_name: str = Field(description="Trimmed, normalized brand name")
    type: str = Field(description="Medicine type ('allopathic' or 'herbal')")
    slug: str = Field(description="URL slug from source database")
    dosage_form: str = Field(description="Dosage form (e.g. 'Tablet', 'Syrup', 'IV Injection')")
    raw_generic: Optional[str] = Field(default=None, description="Raw generic composition string")
    raw_strength: Optional[str] = Field(default=None, description="Raw strength string")
    manufacturer: str = Field(description="Pharmaceutical manufacturer name")
    raw_package_container: Optional[str] = Field(default=None, description="Raw package container and pricing string")
    raw_package_size: Optional[str] = Field(default=None, description="Raw secondary Package Size column (nullable)")
