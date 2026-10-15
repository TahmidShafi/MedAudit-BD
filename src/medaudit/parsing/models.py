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
