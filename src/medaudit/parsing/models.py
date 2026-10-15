"""Domain models for parsed generic and strength structures, plus parse anomaly logging."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ParseAnomaly(BaseModel):
    """Structured parse anomaly representation matching the parse_anomalies table."""
    model_config = ConfigDict(frozen=True)

    anomaly_id: Optional[int] = Field(default=None, description="Optional surrogate identifier")
    product_id: Optional[int] = Field(default=None, description="FK to ProductRecord.product_id if known")
    module: str = Field(description="Module name: 'generic', 'strength', or 'price'")
    reason_code: str = Field(description="Structured reason code (e.g. MISSING_GENERIC, COMPONENT_COUNT_MISMATCH)")
    raw_string: Optional[str] = Field(default=None, description="The raw unparseable string")
    details: Optional[str] = Field(default=None, description="Diagnostic contextual details")


class GenericComponent(BaseModel):
    """A single active ingredient component within a generic formulation."""
    model_config = ConfigDict(frozen=True)

    component_order: int = Field(description="1-based component order in compound generics")
    raw_component: str = Field(description="Original unstripped substring for this component")
    canonical_generic: str = Field(description="Standardized active moiety (lowercase, INN mapped)")
    salt: Optional[str] = Field(default=None, description="Extracted chemical radical, ester, or hydrate")
    annotation: Optional[str] = Field(default=None, description="Stripped bracketed or parenthesized tags")
    is_nti: bool = Field(default=False, description="Flag for Narrow Therapeutic Index active ingredients")


class ParsedGeneric(BaseModel):
    """Complete parsed generic outcome for a product SKU."""
    model_config = ConfigDict(frozen=True)

    raw_generic: Optional[str] = Field(default=None, description="Original raw generic string")
    components: List[GenericComponent] = Field(default_factory=list, description="Parsed components")
    is_compound: bool = Field(default=False, description="True if compound generic containing '+'")
    anomalies: List[ParseAnomaly] = Field(default_factory=list, description="Any parsing anomalies encountered")

    @property
    def is_valid(self) -> bool:
        """True if at least one component was successfully parsed with a canonical generic."""
        return len(self.components) > 0 and all(bool(c.canonical_generic) for c in self.components)

    @property
    def canonical_formula(self) -> str:
        """Join all canonical component generics with ' + '."""
        return " + ".join(c.canonical_generic for c in self.components)


class ComponentStrength(BaseModel):
    """Normalized strength representation for a single active component."""
    model_config = ConfigDict(frozen=True)

    component_order: int = Field(description="1-based component order matching generic component order")
    raw_strength: str = Field(description="Raw component strength substring")
    amount: Optional[float] = Field(default=None, description="Primary numerical amount")
    amount_unit: Optional[str] = Field(default=None, description="Standardized unit (mg, mcg, g, %, IU, CFU)")
    denominator_amount: Optional[float] = Field(default=None, description="Denominator volume or delivery unit count")
    denominator_unit: Optional[str] = Field(default=None, description="Denominator unit (ml, puff, spray, dose, vial)")
    normalized_mg: Optional[float] = Field(default=None, description="Normalized absolute mass in milligrams")
    normalized_concentration_mg_per_ml: Optional[float] = Field(
        default=None, description="Normalized concentration in mg/ml for liquid solutions/suspensions"
    )


class ParsedStrength(BaseModel):
    """Complete parsed strength representation for a product SKU."""
    model_config = ConfigDict(frozen=True)

    raw_strength: Optional[str] = Field(default=None, description="Original raw strength string")
    components: List[ComponentStrength] = Field(default_factory=list, description="Parsed component strengths")
    is_compound: bool = Field(default=False, description="True if multi-component strength")
    anomalies: List[ParseAnomaly] = Field(default_factory=list, description="Any parsing anomalies encountered")

    @property
    def is_valid(self) -> bool:
        """True if all components have non-null amounts."""
        return len(self.components) > 0 and all(c.amount is not None for c in self.components)


class PricePack(BaseModel):
    """Structured representation of a single pharmaceutical packaging and pricing tier."""
    model_config = ConfigDict(frozen=True)

    product_id: Optional[int] = Field(default=None, description="FK to ProductRecord.product_id if known")
    container_type: str = Field(
        description="Packaging container form (e.g. 'pack', 'bottle', 'vial', 'ampoule', 'tube', 'drop', 'spray', 'inhaler', 'cartridge', 'pen', 'sachet', 'container', 'unit_only', 'other')"
    )
    volume_or_weight_value: Optional[float] = Field(default=None, description="Parsed numerical volume or weight quantity")
    volume_or_weight_unit: Optional[str] = Field(default=None, description="Standardized volume or weight unit (ml, gm, mg, l, dose, spray, unit)")
    pack_qty: Optional[int] = Field(default=None, description="Total discrete delivery units in pack (tablets, capsules, sachets, ampoules, vials)")
    unit_price_bdt: Optional[float] = Field(default=None, description="Stated or calculated price per single unit in Bangladeshi Taka")
    pack_price_bdt: Optional[float] = Field(default=None, description="Stated price for entire package in Bangladeshi Taka")
    normalized_unit_price_bdt: Optional[float] = Field(default=None, description="Standardized comparable unit price in Bangladeshi Taka based on comparison_unit")
    comparison_unit: str = Field(description="Standardized comparison basis ('per_unit', 'per_ml', 'per_gm', 'per_l', 'per_dose')")
    residual_band: str = Field(
        default="SINGLE_PRICE_NO_PACK_CHECK",
        description="Arithmetic residual classification: 'BAND_1_EXACT', 'BAND_2_ROUNDING_DRIFT', 'BAND_3_HARD_DISCREPANCY', 'SINGLE_PRICE_NO_PACK_CHECK'"
    )
    residual_delta: Optional[float] = Field(default=None, description="Absolute residual abs(unit_price * pack_qty - pack_price)")
    source_span: Optional[str] = Field(default=None, description="Exact raw text segment this pack was parsed from")


class ParsedPrice(BaseModel):
    """Complete parsed price representation for a product SKU containing one or more pack tiers."""
    model_config = ConfigDict(frozen=True)

    product_id: Optional[int] = Field(default=None, description="FK to ProductRecord.product_id if known")
    raw_package_container: Optional[str] = Field(default=None, description="Raw package container string")
    raw_package_size: Optional[str] = Field(default=None, description="Raw package size string")
    packs: List[PricePack] = Field(default_factory=list, description="Parsed price packs/tiers")
    anomalies: List[ParseAnomaly] = Field(default_factory=list, description="Any parsing anomalies encountered")

    @property
    def is_valid(self) -> bool:
        """True if at least one pack was parsed with a positive normalized unit price."""
        return len(self.packs) > 0 and all(
            p.normalized_unit_price_bdt is not None and p.normalized_unit_price_bdt > 0
            for p in self.packs
        )

