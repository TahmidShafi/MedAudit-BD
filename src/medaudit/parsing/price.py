"""Pharmaceutical packaging and pricing parser for MedAudit BD.

Tokenizes package containers, standardizes container taxonomies, normalizes unit prices,
and executes the 3-Band Arithmetic Residual Classifier.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from medaudit.parsing.models import ParseAnomaly, ParsedPrice, PricePack

# Standardized allowed container types
ALLOWED_CONTAINER_TYPES = {
    "pack",
    "bottle",
    "vial",
    "ampoule",
    "tube",
    "drop",
    "spray",
    "inhaler",
    "cartridge",
    "pen",
    "sachet",
    "container",
    "unit_only",
    "other",
}

# Standardized allowed comparison units
ALLOWED_COMPARISON_UNITS = {
    "per_unit",
    "per_ml",
    "per_gm",
    "per_l",
    "per_dose",
}

# Container taxonomy mapping from raw source strings to canonical container types
CONTAINER_MAP = {
    "bottle": "bottle",
    "botttle": "bottle",
    "in bottle": "bottle",
    "spray bottle": "bottle",
    "roll-on bottle": "bottle",
    "syrup": "bottle",
    "suspension": "bottle",
    "solution": "bottle",
    "tube": "tube",
    "gel": "tube",
    "ointment": "tube",
    "drop": "drop",
    "drops": "drop",
    "vial": "vial",
    "vial with wfi": "vial",
    "mesna": "vial",
    "ampoule": "ampoule",
    "ampoules": "ampoule",
    "bag": "container",
    "container": "container",
    "jar": "container",
    "pot": "container",
    "sachet": "sachet",
    "sachets": "sachet",
    "cartridge": "cartridge",
    "cartridges": "cartridge",
    "penfill": "cartridge",
    "pen cartridge": "cartridge",
    "pen": "pen",
    "biopen": "pen",
    "flexpen": "pen",
    "flextouch": "pen",
    "kwikpen": "pen",
    "penset": "pen",
    "pen device": "pen",
    "pre-filled pen": "pen",
    "prefilled pen": "pen",
    "per-filled pen": "pen",
    "kit pen": "pen",
    "syringe": "other",
    "pre-filled syringe": "other",
    "prefilled syringe": "other",
    "oral applicator": "other",
    "pre-filled oral applicator": "other",
    "bar": "other",
    "kit": "other",
    "combipack": "other",
    "tablet kit": "other",
    "pack": "pack",
    "strip": "pack",
    "blister": "pack",
    "tin": "pack",
    "can": "pack",
    "tablet pack": "pack",
    "inhaler": "inhaler",
    "maxhaler": "inhaler",
    "puffs": "inhaler",
    "spray": "spray",
}

# Regex pattern for recognized volume/weight units
UNIT_PATTERN = (
    r"(?:ml|mcl|gm|g|mg|mcg|µg|ug|kg|l|liter|liters|litre|litres|litter|litters|"
    r"unit|units|million\s+units?|lac\s+units?|iu|miu|billion|doses?|sprays?|puffs?)"
)

# Lookahead regex to split multiple package tiers without splitting inside parentheticals
TIER_SPLIT_REGEX = re.compile(
    r",,+|,\s*(?=(?:Unit Price|Each\s+[a-zA-Z\s]+:|"
    r"(?:\d+(?:\.\d+)?\s*" + UNIT_PATTERN + r"\b)|"
    r"(?:\d+\s+(?:tablet|capsule|sachet)\b)|"
    r"(?:\d+[\'’]?s\s+(?:strip|can|tin|pot|blister|pack|bottle)\b)|"
    r"(?:\(\s*\d+[^)]*?(?:\+|&))))",
    re.IGNORECASE,
)


def _parse_float(s: str) -> float:
    """Strip thousand commas and parse clean floating point number."""
    return float(s.replace(",", "").strip())


def _classify_residual(unit_price: float, pack_qty: int, pack_price: float) -> Tuple[str, float]:
    """Execute the 3-Band Arithmetic Residual Classifier.

    Whenever both unit_price_bdt, pack_qty, and pack_price_bdt are explicitly stated:
    delta = round(abs(unit_price * pack_qty - pack_price), 4)
    - BAND_1_EXACT: delta <= 0.001
    - BAND_2_ROUNDING_DRIFT: 0.001 < delta <= 0.01 * pack_qty
    - BAND_3_HARD_DISCREPANCY: delta > 0.01 * pack_qty
    """
    delta = round(abs(unit_price * pack_qty - pack_price), 4)
    tolerance = round(0.01 * pack_qty, 4)
    if delta <= 0.001:
        return "BAND_1_EXACT", delta
    elif delta <= tolerance:
        return "BAND_2_ROUNDING_DRIFT", delta
    else:
        return "BAND_3_HARD_DISCREPANCY", delta


def _parse_tier(tier: str, product_id: Optional[int] = None) -> Optional[PricePack]:
    """Parse a single tier substring into a structured PricePack model."""
    tier_raw = tier.strip().rstrip(",")
    if not tier_raw or tier_raw.lower() in ["not for sale", "price unavailable", "nan", "none"]:
        return None

    # Strip auxiliary parentheticals (flavors, demographics, accessories)
    # Preserves (refill) and (N's pack: ...)
    tier_clean = re.sub(
        r"\s*\((?:with\s+[^\)]+|without\s+[^\)]+|for\s+[^\)]+|lemon|mango|orange|strawberry|atomizer|trigger)\)",
        "",
        tier_raw,
        flags=re.IGNORECASE,
    )

    # 1. Contraceptive Blisters / Combination Packs:
    # E.g.: (21 white+7 brown) tablet: ৳ 23.52, ( 21 white+7 brown) tablet, (1 & 60) tablet kit: ৳ 990.00
    m_combo = re.match(
        r"^\(\s*(\d+)(?:\s+[a-zA-Z\s]+?)?\s*(?:\+|&)\s*(\d+)(?:\s+[a-zA-Z\s]+?)?\)\s+(?:tablet|capsule|pack|kit)(?:\s+kit)?:\s*৳\s*([0-9,.]+)",
        tier_clean,
        re.IGNORECASE,
    )
    if m_combo:
        qty1 = int(m_combo.group(1))
        qty2 = int(m_combo.group(2))
        pack_qty = qty1 + qty2
        pack_price = _parse_float(m_combo.group(3))
        unit_price = round(pack_price / pack_qty, 4)
        c_type = "other" if "kit" in tier_clean.lower() else "pack"
        return PricePack(
            product_id=product_id,
            container_type=c_type,
            volume_or_weight_value=None,
            volume_or_weight_unit=None,
            pack_qty=pack_qty,
            unit_price_bdt=unit_price,
            pack_price_bdt=pack_price,
            normalized_unit_price_bdt=unit_price,
            comparison_unit="per_unit",
            residual_band="SINGLE_PRICE_NO_PACK_CHECK",
            residual_delta=None,
            source_span=tier_raw,
        )

    # 2. Metered Inhalers / Sprays / Maxhalers / Puffs:
    # E.g.: 200 metered doses: ৳ 250.00, 200 metered doses (refill): ৳ 220.00, 120 metered sprays: ৳ 250.00
    m_metered = re.match(
        r"^(\d+(?:\.\d+)?)\s*(?:metered\s+)?(doses?|sprays?|puffs?)(?:\s+(?:maxhaler|inhaler))?(?:\s*\((?:refill|[^\)]+)\))?:\s*৳\s*([0-9,.]+)",
        tier_clean,
        re.IGNORECASE,
    )
    if m_metered:
        doses = float(m_metered.group(1))
        unit_raw = m_metered.group(2).lower()
        if "spray" in unit_raw:
            c_type = "spray"
            v_unit = "spray"
        elif "puff" in unit_raw:
            c_type = "inhaler"
            v_unit = "dose"
        else:
            c_type = "inhaler"
            v_unit = "dose"
        pack_price = _parse_float(m_metered.group(3))
        norm_price = round(pack_price / doses, 4)
        return PricePack(
            product_id=product_id,
            container_type=c_type,
            volume_or_weight_value=doses,
            volume_or_weight_unit=v_unit,
            pack_qty=None,
            unit_price_bdt=None,
            pack_price_bdt=pack_price,
            normalized_unit_price_bdt=norm_price,
            comparison_unit="per_dose",
            residual_band="SINGLE_PRICE_NO_PACK_CHECK",
            residual_delta=None,
            source_span=tier_raw,
        )

    # 3. Tablet Kit / Combipack:
    # E.g.: 1 tablet kit: ৳ 1,500.00, 5 tablet kit: ৳ 300.90, 3 tablet combipack: ৳ 1,600.00
    m_kit = re.match(r"^(\d+)\s+(?:tablet|capsule)\s+(?:kit|combipack):\s*৳\s*([0-9,.]+)", tier_clean, re.IGNORECASE)
    if m_kit:
        qty = int(m_kit.group(1))
        pack_price = _parse_float(m_kit.group(2))
        unit_price = round(pack_price / qty, 4)
        return PricePack(
            product_id=product_id,
            container_type="other",
            volume_or_weight_value=None,
            volume_or_weight_unit=None,
            pack_qty=qty,
            unit_price_bdt=unit_price,
            pack_price_bdt=pack_price,
            normalized_unit_price_bdt=unit_price,
            comparison_unit="per_unit",
            residual_band="SINGLE_PRICE_NO_PACK_CHECK",
            residual_delta=None,
            source_span=tier_raw,
        )

    # 4. Discrete Unit Pack / Tin / Can / Strip / Pot:
    # E.g.: 22 tablet pack: ৳ 130.00, 100's strip: ৳ 40.00, 1000's tin: ৳ 93.38, 30's can: ৳ 120.00
    m_discrete = re.match(
        r"^(?:(\d+)\s+(?:tablet|capsule|pill|sachet)\s+(?:in\s+(?:a\s+)?)?(?:pack|strip|pot|bottle|blister|box)|"
        r"(\d+)[\'’]?s\s+(?:strip|can|tin|pot|blister|pack|bottle|box)):\s*৳\s*([0-9,.]+)",
        tier_clean,
        re.IGNORECASE,
    )
    if m_discrete:
        qty_str = m_discrete.group(1) or m_discrete.group(2)
        qty = int(qty_str)
        pack_price = _parse_float(m_discrete.group(3))
        unit_price = round(pack_price / qty, 4)
        return PricePack(
            product_id=product_id,
            container_type="pack",
            volume_or_weight_value=None,
            volume_or_weight_unit=None,
            pack_qty=qty,
            unit_price_bdt=unit_price,
            pack_price_bdt=pack_price,
            normalized_unit_price_bdt=unit_price,
            comparison_unit="per_unit",
            residual_band="SINGLE_PRICE_NO_PACK_CHECK",
            residual_delta=None,
            source_span=tier_raw,
        )

    # 5. Unit Price with explicit multi-pack tier:
    # E.g.: Unit Price: ৳ 700.00,(28's pack: ৳ 19,600.00)
    m_unit_pack = re.match(
        r"^(?:Unit Price|Each\s+[a-zA-Z\s]+):\s*৳\s*([0-9,.]+),\s*\((\d+)[\'’]s\s+pack:\s*৳\s*([0-9,.]+)\)$",
        tier_clean,
        re.IGNORECASE,
    )
    if m_unit_pack:
        unit_price = _parse_float(m_unit_pack.group(1))
        pack_qty = int(m_unit_pack.group(2))
        pack_price = _parse_float(m_unit_pack.group(3))
        r_band, delta = _classify_residual(unit_price, pack_qty, pack_price)
        return PricePack(
            product_id=product_id,
            container_type="pack",
            volume_or_weight_value=None,
            volume_or_weight_unit=None,
            pack_qty=pack_qty,
            unit_price_bdt=unit_price,
            pack_price_bdt=pack_price,
            normalized_unit_price_bdt=unit_price,
            comparison_unit="per_unit",
            residual_band=r_band,
            residual_delta=delta,
            source_span=tier_raw,
        )

    # 5b. Unit only: Unit Price: ৳ 195.00
    m_unit_only = re.match(
        r"^(?:Unit Price|Each\s+[a-zA-Z\s]+):\s*৳\s*([0-9,.]+)$",
        tier_clean,
        re.IGNORECASE,
    )
    if m_unit_only:
        unit_price = _parse_float(m_unit_only.group(1))
        return PricePack(
            product_id=product_id,
            container_type="unit_only",
            volume_or_weight_value=None,
            volume_or_weight_unit=None,
            pack_qty=None,
            unit_price_bdt=unit_price,
            pack_price_bdt=None,
            normalized_unit_price_bdt=unit_price,
            comparison_unit="per_unit",
            residual_band="SINGLE_PRICE_NO_PACK_CHECK",
            residual_delta=None,
            source_span=tier_raw,
        )

    # 5c. Sachet without volume: 1 sachet: ৳ 19.00,(20's pack: ৳ 380.00)
    m_sachet_unit = re.match(
        r"^1\s+sachet:\s*৳\s*([0-9,.]+)(?:,\s*\((\d+)[\'’]s\s+pack:\s*৳\s*([0-9,.]+)\))?$",
        tier_clean,
        re.IGNORECASE,
    )
    if m_sachet_unit:
        u_price = _parse_float(m_sachet_unit.group(1))
        p_qty_str = m_sachet_unit.group(2)
        p_price_str = m_sachet_unit.group(3)
        if p_qty_str and p_price_str:
            p_qty = int(p_qty_str)
            p_price = _parse_float(p_price_str)
            r_band, delta = _classify_residual(u_price, p_qty, p_price)
            return PricePack(
                product_id=product_id,
                container_type="sachet",
                volume_or_weight_value=None,
                volume_or_weight_unit=None,
                pack_qty=p_qty,
                unit_price_bdt=u_price,
                pack_price_bdt=p_price,
                normalized_unit_price_bdt=u_price,
                comparison_unit="per_unit",
                residual_band=r_band,
                residual_delta=delta,
                source_span=tier_raw,
            )
        else:
            return PricePack(
                product_id=product_id,
                container_type="sachet",
                volume_or_weight_value=None,
                volume_or_weight_unit=None,
                pack_qty=None,
                unit_price_bdt=u_price,
                pack_price_bdt=u_price,
                normalized_unit_price_bdt=u_price,
                comparison_unit="per_unit",
                residual_band="SINGLE_PRICE_NO_PACK_CHECK",
                residual_delta=None,
                source_span=tier_raw,
            )

    # 6. Volume / Weight / Biological Unit Container:
    # E.g.: 5 ml ampoule: ৳ 100.00,(5's pack: ৳ 500.00), 60 ml bottle: ৳ 70.23, 100 unit vial: ৳ 26,815.28
    m_vol = re.match(
        r"^(\d+(?:\.\d+)?)\s*(" + UNIT_PATTERN + r")\s+([a-zA-Z\s-]+?):\s*৳\s*([0-9,.]+)(?:,\s*\((\d+)[\'’]s\s+pack:\s*৳\s*([0-9,.]+)\))?$",
        tier_clean,
        re.IGNORECASE,
    )
    if m_vol:
        vol_val = float(m_vol.group(1))
        vol_u_raw = m_vol.group(2).lower()
        if vol_u_raw in ["l", "liter", "liters", "litre", "litres", "litter", "litters"]:
            vol_u = "l"
        elif vol_u_raw in ["unit", "units", "lac unit", "lac units", "million unit", "million units"]:
            vol_u = "dose"
        elif vol_u_raw in ["gm", "g"]:
            vol_u = "gm"
        elif vol_u_raw == "kg":
            vol_u = "gm"
            vol_val = vol_val * 1000.0
        elif vol_u_raw in ["mcl"]:
            vol_u = "ml"
            vol_val = round(vol_val / 1000.0, 6)
        elif vol_u_raw in ["mcg", "µg", "ug"]:
            vol_u = "mg"
            vol_val = round(vol_val / 1000.0, 6)
        else:
            vol_u = vol_u_raw

        raw_c = m_vol.group(3).strip().lower()
        c_type = CONTAINER_MAP.get(raw_c, "other")
        price1 = _parse_float(m_vol.group(4))
        pack_qty_str = m_vol.group(5)
        pack_price_str = m_vol.group(6)

        if pack_qty_str and pack_price_str:
            pack_qty = int(pack_qty_str)
            pack_price = _parse_float(pack_price_str)
            unit_price = price1
            r_band, delta = _classify_residual(unit_price, pack_qty, pack_price)
            return PricePack(
                product_id=product_id,
                container_type=c_type,
                volume_or_weight_value=vol_val,
                volume_or_weight_unit=vol_u,
                pack_qty=pack_qty,
                unit_price_bdt=unit_price,
                pack_price_bdt=pack_price,
                normalized_unit_price_bdt=unit_price,
                comparison_unit="per_unit",
                residual_band=r_band,
                residual_delta=delta,
                source_span=tier_raw,
            )
        else:
            pack_price = price1
            if c_type in {"pen", "vial", "ampoule", "cartridge", "other"}:
                comp_unit = "per_unit"
                norm_price = pack_price
            elif vol_u == "ml":
                comp_unit = "per_ml"
                norm_price = round(pack_price / vol_val, 4)
            elif vol_u == "gm":
                comp_unit = "per_gm"
                norm_price = round(pack_price / vol_val, 4)
            elif vol_u == "l":
                comp_unit = "per_l"
                norm_price = round(pack_price / vol_val, 4)
            else:
                comp_unit = "per_unit"
                norm_price = pack_price

            return PricePack(
                product_id=product_id,
                container_type=c_type,
                volume_or_weight_value=vol_val,
                volume_or_weight_unit=vol_u,
                pack_qty=None,
                unit_price_bdt=None,
                pack_price_bdt=pack_price,
                normalized_unit_price_bdt=norm_price,
                comparison_unit=comp_unit,
                residual_band="SINGLE_PRICE_NO_PACK_CHECK",
                residual_delta=None,
                source_span=tier_raw,
            )

    # 7. Fallback single pack format: (50's pack: ৳ 500.00)
    m_fallback_pack = re.match(r"^\(?(\d+)[\'’]?s?\s+pack:\s*৳\s*([0-9,.]+)\)?$", tier_clean, re.IGNORECASE)
    if m_fallback_pack:
        qty = int(m_fallback_pack.group(1))
        pack_price = _parse_float(m_fallback_pack.group(2))
        unit_price = round(pack_price / qty, 4)
        return PricePack(
            product_id=product_id,
            container_type="pack",
            volume_or_weight_value=None,
            volume_or_weight_unit=None,
            pack_qty=qty,
            unit_price_bdt=unit_price,
            pack_price_bdt=pack_price,
            normalized_unit_price_bdt=unit_price,
            comparison_unit="per_unit",
            residual_band="SINGLE_PRICE_NO_PACK_CHECK",
            residual_delta=None,
            source_span=tier_raw,
        )

    return None


def parse_price(
    raw_package_container: Optional[str],
    raw_package_size: Optional[str] = None,
    product_id: Optional[int] = None,
) -> ParsedPrice:
    """Parse raw package container and size strings into structured ParsedPrice models.

    Args:
        raw_package_container: Complete container description string from 'package container' column.
        raw_package_size: Optional fallback string from 'Package Size' column.
        product_id: Optional SKU product identifier.

    Returns:
        Structured ParsedPrice containing parsed PricePack objects and any diagnostic ParseAnomaly objects.
    """
    clean_c = (
        str(raw_package_container).strip()
        if raw_package_container is not None and str(raw_package_container).strip() not in ["", "nan", "None"]
        else None
    )
    clean_s = (
        str(raw_package_size).strip()
        if raw_package_size is not None and str(raw_package_size).strip() not in ["", "nan", "None"]
        else None
    )

    # Choose primary source text
    primary_text = clean_c or clean_s or ""

    if not primary_text or primary_text.lower() in ["price unavailable", "not for sale"]:
        reason = "PRICE_UNAVAILABLE" if "price unavailable" in primary_text.lower() or not primary_text else "NOT_FOR_SALE"
        anomaly = ParseAnomaly(
            product_id=product_id,
            module="price",
            reason_code=reason,
            raw_string=primary_text or None,
            details="Price is unavailable or SKU is marked not for retail sale",
        )
        return ParsedPrice(
            product_id=product_id,
            raw_package_container=clean_c,
            raw_package_size=clean_s,
            packs=[],
            anomalies=[anomaly] if primary_text else [],
        )

    # Split into candidate tiers
    parts = [p.strip().rstrip(",") for p in TIER_SPLIT_REGEX.split(primary_text) if p.strip().rstrip(",")]

    packs: List[PricePack] = []
    anomalies: List[ParseAnomaly] = []

    for part in parts:
        pack = _parse_tier(part, product_id=product_id)
        if pack is not None:
            packs.append(pack)
            if pack.residual_band == "BAND_3_HARD_DISCREPANCY":
                anomalies.append(
                    ParseAnomaly(
                        product_id=product_id,
                        module="price",
                        reason_code="ARITHMETIC_RESIDUAL_BAND_3",
                        raw_string=part,
                        details=(
                            f"Arithmetic residual delta {pack.residual_delta} exceeds "
                            f"0.01 * pack_qty ({round(0.01 * (pack.pack_qty or 1), 4)})"
                        ),
                    )
                )
        else:
            if part.lower() not in ["not for sale", "price unavailable"]:
                anomalies.append(
                    ParseAnomaly(
                        product_id=product_id,
                        module="price",
                        reason_code="UNPARSEABLE_PRICE_TOKEN",
                        raw_string=part,
                        details="Unable to tokenize pricing tier into recognized packaging schema",
                    )
                )

    return ParsedPrice(
        product_id=product_id,
        raw_package_container=clean_c,
        raw_package_size=clean_s,
        packs=packs,
        anomalies=anomalies,
    )

