"""Pydantic v2 schemas for MedAudit BD REST API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    """Health check endpoint response schema."""

    status: str = Field(default="ok", description="Service status")
    database_connected: bool = Field(description="SQLite database connectivity flag")
    table_counts: Dict[str, int] = Field(description="Exact row counts for primary database tables")


class BrandSearchItem(BaseModel):
    """Individual SKU search match item."""

    product_id: int
    brand_id: int
    brand_name: str
    dosage_form: str
    strength: Optional[str] = None
    manufacturer: str
    similarity_score: float


class PrescriptionItemInput(BaseModel):
    """Prescription item input supporting direct product_id or structured query attributes."""

    product_id: Optional[int] = Field(default=None, description="Direct catalog product ID")
    brand: Optional[str] = Field(default=None, description="Brand name query")
    brand_name: Optional[str] = Field(default=None, description="Brand name query alias")
    strength: Optional[str] = Field(default=None, description="Desired strength (e.g. '500 mg')")
    form: Optional[str] = Field(default=None, description="Desired dosage form (e.g. 'Tablet')")
    dosage_form: Optional[str] = Field(default=None, description="Desired dosage form alias")

    def to_audit_item(self) -> Dict[str, Any] | int:
        """Convert input model to engine-compatible item."""
        if self.product_id is not None:
            return self.product_id
        d: Dict[str, Any] = {}
        b = self.brand or self.brand_name
        if b:
            d["brand_name"] = b
        f = self.form or self.dosage_form
        if f:
            d["dosage_form"] = f
        if self.strength:
            d["strength"] = self.strength
        return d


class PrescriptionAuditRequest(BaseModel):
    """Prescription audit request validating 2 to 8 items."""

    items: List[PrescriptionItemInput] = Field(
        description="List of 2 to 8 prescribed pharmaceutical items"
    )
    manufacturer_filter: Optional[str] = Field(
        default=None, description="Optional manufacturer filter for alternative ranking"
    )

    @field_validator("items")
    @classmethod
    def validate_item_count(cls, v: List[PrescriptionItemInput]) -> List[PrescriptionItemInput]:
        if len(v) < 2 or len(v) > 8:
            raise ValueError(f"Prescription must contain between 2 and 8 items, got {len(v)}")
        return v


class PrescriptionAuditResponse(BaseModel):
    """Structured prescription audit output with per-check statuses and statutory disclaimer."""

    overall_status: str
    disclaimer: str
    checks: Dict[str, str] = Field(
        description="High-level status per check: resolution, duplicate_generics, release_and_strength_hazards, nti_locks, alternatives, lasa_warnings"
    )
    item_count: int
    explanation: Optional[str] = None
    ambiguous_items: Optional[List[Dict[str, Any]]] = None
    unresolved_items: Optional[List[Dict[str, Any]]] = None
    duplicate_check: Optional[Dict[str, Any]] = None
    intra_prescription_hazards: Optional[List[Dict[str, Any]]] = None
    shelf_lookalike_hazards: Optional[List[Dict[str, Any]]] = None
    intra_prescription_lasa_hazards: Optional[List[Dict[str, Any]]] = None
    items: Optional[List[Dict[str, Any]]] = None


class BrandLASAWarningItem(BaseModel):
    """Precomputed LASA warning entry."""

    confused_brand_name: str
    confused_manufacturer: str
    tier: int
    tier_name: str
    edit_similarity: float
    phonetic_match: bool
    same_generic: bool
    generic_priority_label: str
    diff_preview: str
    disclaimer: str


class BrandLASAResponse(BaseModel):
    """Response containing precomputed LASA pairs for a requested brand."""

    brand_id: int
    brand_name: str
    manufacturer: str
    warnings_count: int
    warnings: List[BrandLASAWarningItem]
