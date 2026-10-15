"""Strength formulation parser and unit normalizer for MedAudit BD.

Parses single and multi-component strengths, slash concentrations, percentages,
mass units (g -> mg conversion), volumes, delivery units, and biological units.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from medaudit.parsing.models import ComponentStrength, ParseAnomaly, ParsedStrength


def _normalize_mass_to_mg(amount: float, unit: str) -> Optional[float]:
    """Convert mass amounts to normalized milligrams (mg)."""
    unit_lower = unit.lower().strip()
    if unit_lower in ["mg", "milligram", "milligrams"]:
        return round(amount, 6)
    if unit_lower in ["g", "gm", "gram", "grams"]:
        return round(amount * 1000.0, 6)
    if unit_lower in ["mcg", "µg", "ug", "\u00b5g", "\u03bcg", "microgram", "micrograms"]:
        return round(amount / 1000.0, 6)
    if unit_lower in ["kg", "kilogram", "kilograms"]:
        return round(amount * 1_000_000.0, 6)
    return None


def _calculate_concentration_mg_per_ml(
    amount: float,
    amount_unit: str,
    denom_amount: float,
    denom_unit: str,
) -> Optional[float]:
    """Calculate concentration in normalized mg/ml."""
    if denom_amount <= 0:
        return None

    denom_u = denom_unit.lower().strip()
    amt_u = amount_unit.lower().strip()

    # Convert denominator to ml
    denom_ml: Optional[float] = None
    if denom_u in ["ml", "milliliter", "milliliters"]:
        denom_ml = denom_amount
    elif denom_u in ["l", "liter", "liters"]:
        denom_ml = denom_amount * 1000.0

    if denom_ml is None:
        return None

    # Convert numerator mass to mg
    norm_mg = _normalize_mass_to_mg(amount, amt_u)
    if norm_mg is not None:
        return round(norm_mg / denom_ml, 6)

    return None


def _parse_single_component_str(raw: str, order: int) -> Tuple[Optional[ComponentStrength], Optional[str]]:
    """Parse an individual component strength token into ComponentStrength.
    
    Returns (ComponentStrength, error_message).
    """
    s = re.sub(r"[\s\xa0]+", " ", raw).strip()
    if not s:
        return None, "Empty strength token"

    # 1. Check Percentage: e.g. '1%', '0.05% w/v', '5% v/v'
    m_pct = re.match(r"^([0-9.]+)\s*%\s*(?:w/[wv]|v/v)?$", s, re.IGNORECASE)
    if m_pct:
        val = float(m_pct.group(1))
        # In pharmacology: 1% w/v = 1 g / 100 ml = 1000 mg / 100 ml = 10 mg/ml
        return ComponentStrength(
            component_order=order,
            raw_strength=s,
            amount=val,
            amount_unit="%",
            denominator_amount=100.0,
            denominator_unit="ml",
            normalized_concentration_mg_per_ml=round(val * 10.0, 6),
        ), None

    # 2. Check Probiotics Billions (e.g. '4 billion', '2.3 billion')
    m_bil = re.match(r"^([0-9.]+)\s*billion(?:\s*cfu)?$", s, re.IGNORECASE)
    if m_bil:
        val = float(m_bil.group(1)) * 1_000_000_000.0
        return ComponentStrength(
            component_order=order,
            raw_strength=s,
            amount=val,
            amount_unit="CFU",
        ), None

    # 3. Check Lac Units / Lakh Units (Indian numbering system: 1 lac = 100,000)
    m_lac = re.match(r"^([0-9.]+)\s*lac\s*(?:iu|units?)?(?:\s*/\s*([a-zA-Z]+))?$", s, re.IGNORECASE)
    if m_lac:
        val = float(m_lac.group(1)) * 100_000.0
        denom_u = m_lac.group(2).lower() if m_lac.group(2) else None
        return ComponentStrength(
            component_order=order,
            raw_strength=s,
            amount=val,
            amount_unit="IU",
            denominator_amount=1.0 if denom_u else None,
            denominator_unit=denom_u,
        ), None

    # 4. Check Million International Units (MIU)
    m_miu = re.match(r"^([0-9.]+)\s*(?:miu|million\s+units?)(?:\s*/\s*([a-zA-Z]+))?$", s, re.IGNORECASE)
    if m_miu:
        val = float(m_miu.group(1)) * 1_000_000.0
        denom_u = m_miu.group(2).lower() if m_miu.group(2) else None
        return ComponentStrength(
            component_order=order,
            raw_strength=s,
            amount=val,
            amount_unit="IU",
            denominator_amount=1.0 if denom_u else None,
            denominator_unit=denom_u,
        ), None

    # 5. Check Slash Concentration: '125 mg/5 ml', '500 mg/vial', '100 mcg/puff', '8000 Anti-Xa IU/0.8 ml'
    m_slash = re.match(
        r"^([0-9.]+)\s*(Anti-Xa\s*IU|[a-zA-Z\u03bc\u00b5%]+(?:\s*IU)?)\s*/\s*([0-9.]+)?\s*([a-zA-Z\s]+)$",
        s,
        re.IGNORECASE,
    )
    if m_slash:
        amt = float(m_slash.group(1))
        amt_unit = m_slash.group(2).strip()
        denom_amt = float(m_slash.group(3)) if m_slash.group(3) else 1.0
        denom_unit = m_slash.group(4).strip()

        norm_mg = _normalize_mass_to_mg(amt, amt_unit)
        norm_conc = _calculate_concentration_mg_per_ml(amt, amt_unit, denom_amt, denom_unit)

        return ComponentStrength(
            component_order=order,
            raw_strength=s,
            amount=amt,
            amount_unit=amt_unit,
            denominator_amount=denom_amt,
            denominator_unit=denom_unit,
            normalized_mg=norm_mg if denom_unit.lower() in ["vial", "ampoule", "container", "bottle"] else None,
            normalized_concentration_mg_per_ml=norm_conc,
        ), None

    # 6. Check Single Mass/Volume/Unit: '500 mg', '1 gm', '10 ml', '100 IU', '20 mcg'
    m_single = re.match(r"^([0-9.]+)\s*([a-zA-Z\u03bc\u00b5%]+)$", s)
    if m_single:
        amt = float(m_single.group(1))
        unit = m_single.group(2).strip()
        norm_mg = _normalize_mass_to_mg(amt, unit)

        return ComponentStrength(
            component_order=order,
            raw_strength=s,
            amount=amt,
            amount_unit=unit,
            normalized_mg=norm_mg,
        ), None

    # 7. Check Biphasic Insulin Percentage In Concentration: e.g. '30%+70% in 100 IU/ml' or single '30% in 100 IU/ml'
    m_ins = re.match(r"^([0-9.]+)\s*%\s+in\s+([0-9.]+)\s*([a-zA-Z/]+)$", s, re.IGNORECASE)
    if m_ins:
        pct_val = float(m_ins.group(1))
        total_iu = float(m_ins.group(2))
        unit_str = m_ins.group(3).strip()
        effective_iu = (pct_val / 100.0) * total_iu
        return ComponentStrength(
            component_order=order,
            raw_strength=s,
            amount=effective_iu,
            amount_unit="IU/ml",
            denominator_amount=1.0,
            denominator_unit="ml",
        ), None

    return None, f"Unrecognized strength format token: '{s}'"


def parse_strength(
    raw_strength: Optional[str],
    generic_component_count: Optional[int] = None,
    product_id: Optional[int] = None,
) -> ParsedStrength:
    """Parse raw strength string into structured ParsedStrength domain model.
    
    Supports multi-component strengths, slash concentrations, percentages,
    mass normalization to milligrams (mg), and anomaly logging.
    """
    if raw_strength is None:
        return ParsedStrength(
            raw_strength=None,
            components=[],
            is_compound=False,
            anomalies=[
                ParseAnomaly(
                    product_id=product_id,
                    module="strength",
                    reason_code="MISSING_STRENGTH",
                    raw_string=None,
                    details="Strength field is null",
                )
            ],
        )

    clean_raw = re.sub(r"[\s\xa0]+", " ", str(raw_strength)).strip()
    if not clean_raw or clean_raw.lower() == "nan":
        return ParsedStrength(
            raw_strength=raw_strength,
            components=[],
            is_compound=False,
            anomalies=[
                ParseAnomaly(
                    product_id=product_id,
                    module="strength",
                    reason_code="MISSING_STRENGTH",
                    raw_string=str(raw_strength),
                    details="Strength string is empty or whitespace",
                )
            ],
        )

    components: List[ComponentStrength] = []
    anomalies: List[ParseAnomaly] = []

    # Case A: Parenthesized compound concentration: e.g. '(10 mg+30 mg+1.25 mg)/5 ml'
    m_parenthesized = re.match(r"^\((.*?)\)\s*/\s*([0-9.]+)?\s*([a-zA-Z\s]+)$", clean_raw)
    if m_parenthesized:
        inner = m_parenthesized.group(1)
        denom_amt_str = m_parenthesized.group(2)
        denom_unit_str = m_parenthesized.group(3).strip()
        denom_full = f"{denom_amt_str} {denom_unit_str}".strip()

        inner_parts = inner.split("+")
        for order, part in enumerate(inner_parts, 1):
            comp_str = f"{part.strip()}/{denom_full}"
            parsed_comp, err = _parse_single_component_str(comp_str, order)
            if parsed_comp:
                components.append(parsed_comp)
            else:
                anomalies.append(
                    ParseAnomaly(
                        product_id=product_id,
                        module="strength",
                        reason_code="UNPARSEABLE_STRENGTH_TOKEN",
                        raw_string=comp_str,
                        details=err,
                    )
                )

        return ParsedStrength(
            raw_strength=raw_strength,
            components=components,
            is_compound=len(components) > 1,
            anomalies=anomalies,
        )

    # Case B: Insulin biphasic mixture: e.g. '30%+70% in 100 IU/ml'
    m_ins_mix = re.match(r"^([0-9.]+%)\s*\+\s*([0-9.]+%)\s+in\s+([0-9.]+)\s*([a-zA-Z/]+)$", clean_raw, re.IGNORECASE)
    if m_ins_mix:
        pct1 = m_ins_mix.group(1)
        pct2 = m_ins_mix.group(2)
        base = f"in {m_ins_mix.group(3)} {m_ins_mix.group(4)}"
        parts = [f"{pct1} {base}", f"{pct2} {base}"]
        for order, part in enumerate(parts, 1):
            parsed_comp, err = _parse_single_component_str(part, order)
            if parsed_comp:
                components.append(parsed_comp)
            else:
                anomalies.append(
                    ParseAnomaly(
                        product_id=product_id,
                        module="strength",
                        reason_code="UNPARSEABLE_STRENGTH_TOKEN",
                        raw_string=part,
                        details=err,
                    )
                )
        return ParsedStrength(
            raw_strength=raw_strength,
            components=components,
            is_compound=True,
            anomalies=anomalies,
        )

    # Case C: Standard compound separated by '+' or '&'
    # Split on '+' or ' & '
    parts = re.split(r"\s*\+\s*|\s+&\s+", clean_raw)
    is_compound = len(parts) > 1

    for order, part in enumerate(parts, 1):
        parsed_comp, err = _parse_single_component_str(part, order)
        if parsed_comp:
            components.append(parsed_comp)
        else:
            anomalies.append(
                ParseAnomaly(
                    product_id=product_id,
                    module="strength",
                    reason_code="UNPARSEABLE_STRENGTH_TOKEN",
                    raw_string=part,
                    details=err,
                )
            )

    # Check alignment with generic components count if provided
    if generic_component_count is not None and generic_component_count > 0:
        if len(components) != generic_component_count:
            anomalies.append(
                ParseAnomaly(
                    product_id=product_id,
                    module="strength",
                    reason_code="COMPONENT_COUNT_MISMATCH",
                    raw_string=clean_raw,
                    details=(
                        f"Generic has {generic_component_count} component(s) "
                        f"but strength parsed into {len(components)} component(s)"
                    ),
                )
            )

    return ParsedStrength(
        raw_strength=raw_strength,
        components=components,
        is_compound=is_compound,
        anomalies=anomalies,
    )
