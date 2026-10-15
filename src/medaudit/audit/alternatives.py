"""Same-generic alternative ranking, price comparison, and NTI substitution locking."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple


def _find_best_matching_pack(
    product_id: int,
    cursor: sqlite3.Cursor,
    target_strength_num: Optional[float] = None,
    target_strength_unit: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Select the most representative PricePack for a product.

    Handles the multi-volume tier edge case (Phase 2B IDs 17285 & 28654):
    If a product lists multiple volume variants (e.g. 30 mg vial vs 100 mg vial),
    matches the pack whose volume_or_weight_value and unit match the SKU's strength.
    """
    cursor.execute(
        """
        SELECT pack_id, container_type, volume_or_weight_value, volume_or_weight_unit,
               pack_qty, unit_price_bdt, pack_price_bdt, normalized_unit_price_bdt,
               comparison_unit, residual_band
        FROM price_packs
        WHERE product_id = ?
        ORDER BY normalized_unit_price_bdt ASC
        """,
        (product_id,),
    )
    packs = cursor.fetchall()
    if not packs:
        return None

    pack_dicts = [
        {
            "pack_id": p[0],
            "container_type": p[1],
            "volume_or_weight_value": p[2],
            "volume_or_weight_unit": p[3],
            "pack_qty": p[4],
            "unit_price_bdt": p[5],
            "pack_price_bdt": p[6],
            "normalized_unit_price_bdt": p[7],
            "comparison_unit": p[8],
            "residual_band": p[9],
        }
        for p in packs
    ]

    # If target strength is known, check for an exact volume/weight match among packs
    if target_strength_num is not None and target_strength_unit:
        for p in pack_dicts:
            v_val = p["volume_or_weight_value"]
            v_unit = p["volume_or_weight_unit"]
            if v_val is not None and v_unit:
                if abs(v_val - target_strength_num) < 0.001 and v_unit.lower() == target_strength_unit.lower():
                    return p

    # Default to the first valid pack
    return pack_dicts[0]


def find_same_generic_alternatives(
    product_id: int,
    conn: sqlite3.Connection,
    manufacturer_filter: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Find and rank cheaper same-generic alternatives for a prescribed product.

    Requirements:
    1. Exact same ordered tuple of canonical generics.
    2. Exact same normalized_strength and dosage_form.
    3. Valid price pack sharing the same comparison_unit.
    4. NTI check: If any active ingredient is NTI, brand substitution is locked.
    5. Price availability check: If price is unparseable or unavailable, returns UNVERIFIED.
    6. Outputs labeled strictly as 'same-generic alternative' (NEVER 'bioequivalent').
    """
    cursor = conn.cursor()

    # 1. Fetch prescribed product details
    cursor.execute(
        """
        SELECT p.product_id, p.raw_brand_name, p.dosage_form, p.normalized_strength,
               p.manufacturer, p.parse_status, p.raw_package_container
        FROM products p
        WHERE p.product_id = ?
        """,
        (product_id,),
    )
    prod_row = cursor.fetchone()
    if not prod_row:
        return {
            "status": "UNVERIFIED",
            "substitution_locked": False,
            "product_id": product_id,
            "explanation": f"Product ID {product_id} was not found in catalog.",
            "alternatives": [],
        }

    p_id, brand_name, dosage_form, norm_strength, manufacturer, parse_status, raw_container = prod_row

    # 2. Fetch generic components & check NTI status
    cursor.execute(
        """
        SELECT canonical_generic, is_nti
        FROM generic_components
        WHERE product_id = ?
        ORDER BY component_order ASC
        """,
        (product_id,),
    )
    gen_rows = cursor.fetchall()
    if not gen_rows:
        return {
            "status": "UNVERIFIED",
            "substitution_locked": False,
            "product_id": product_id,
            "brand_name": brand_name,
            "explanation": "Prescribed product has missing or unparsed generic formulation (MISSING_GENERIC).",
            "alternatives": [],
        }

    canonical_generics = [r[0] for r in gen_rows]
    is_any_nti = any(r[1] == 1 for r in gen_rows)

    if is_any_nti:
        nti_names = [r[0] for r in gen_rows if r[1] == 1]
        return {
            "status": "LOCKED",
            "substitution_locked": True,
            "product_id": product_id,
            "brand_name": brand_name,
            "canonical_generics": canonical_generics,
            "dosage_form": dosage_form,
            "normalized_strength": norm_strength,
            "explanation": (
                f"Narrow Therapeutic Index drug ({', '.join(nti_names)}): minor differences in dose or "
                f"concentration can lead to serious adverse reactions or therapeutic failures. "
                f"Brand substitution is strictly locked."
            ),
            "alternatives": [],
        }

    # 3. Check price pack of prescribed product
    cursor.execute(
        """
        SELECT sc.numeric_value, sc.canonical_unit
        FROM strength_components sc
        WHERE sc.product_id = ? AND sc.component_order = 1
        """,
        (product_id,),
    )
    s_row = cursor.fetchone()
    s_num = s_row[0] if s_row else None
    s_unit = s_row[1] if s_row else None

    prescribed_pack = _find_best_matching_pack(
        product_id, cursor, target_strength_num=s_num, target_strength_unit=s_unit
    )

    if not prescribed_pack or prescribed_pack.get("normalized_unit_price_bdt") is None:
        # Check anomaly reason
        cursor.execute(
            "SELECT reason_code FROM parse_anomalies WHERE product_id = ? AND module = 'price'",
            (product_id,),
        )
        anom_row = cursor.fetchone()
        reason = anom_row[0] if anom_row else "PRICE_UNAVAILABLE"
        return {
            "status": "UNVERIFIED",
            "substitution_locked": False,
            "product_id": product_id,
            "brand_name": brand_name,
            "canonical_generics": canonical_generics,
            "explanation": (
                f"Prescribed product has no valid verified price in the catalog (Reason: {reason}). "
                f"Cannot compute cost differentials."
            ),
            "alternatives": [],
        }

    prescribed_price = prescribed_pack["normalized_unit_price_bdt"]
    prescribed_comp_unit = prescribed_pack["comparison_unit"]

    # 4. Query candidate products with exact same dosage form and normalized strength
    cursor.execute(
        """
        SELECT p.product_id, p.raw_brand_name, p.manufacturer
        FROM products p
        WHERE p.dosage_form = ? AND p.normalized_strength = ? AND p.product_id != ?
        """,
        (dosage_form, norm_strength, product_id),
    )
    candidates = cursor.fetchall()

    alternatives: List[Dict[str, Any]] = []

    for c_id, c_brand, c_mfg in candidates:
        if manufacturer_filter and c_mfg.strip().lower() != manufacturer_filter.strip().lower():
            continue

        # Check candidate generic components exact match
        cursor.execute(
            """
            SELECT canonical_generic
            FROM generic_components
            WHERE product_id = ?
            ORDER BY component_order ASC
            """,
            (c_id,),
        )
        c_generics = [r[0] for r in cursor.fetchall()]
        if c_generics != canonical_generics:
            continue

        # Check candidate price pack matching comparison_unit
        c_pack = _find_best_matching_pack(
            c_id, cursor, target_strength_num=s_num, target_strength_unit=s_unit
        )
        if not c_pack or c_pack.get("normalized_unit_price_bdt") is None:
            continue
        if c_pack["comparison_unit"] != prescribed_comp_unit:
            continue
        if c_pack["residual_band"] not in {"BAND_1_EXACT", "BAND_2_ROUNDING_DRIFT", "SINGLE_PRICE_NO_PACK_CHECK"}:
            continue

        cand_price = c_pack["normalized_unit_price_bdt"]
        savings_bdt = round(prescribed_price - cand_price, 4)
        savings_pct = round((savings_bdt / prescribed_price) * 100.0, 2) if prescribed_price > 0 else 0.0

        alternatives.append({
            "product_id": c_id,
            "brand_name": c_brand,
            "manufacturer": c_mfg,
            "dosage_form": dosage_form,
            "normalized_strength": norm_strength,
            "relationship": "same-generic alternative",
            "comparison_unit": prescribed_comp_unit,
            "normalized_unit_price_bdt": cand_price,
            "pack_price_bdt": c_pack.get("pack_price_bdt"),
            "pack_qty": c_pack.get("pack_qty"),
            "savings_bdt": savings_bdt,
            "savings_pct": savings_pct,
            "is_cheaper": savings_bdt > 0.0001,
        })

    # Sort alternatives by price ascending
    alternatives.sort(key=lambda x: x["normalized_unit_price_bdt"])
    if limit > 0:
        alternatives = alternatives[:limit]

    return {
        "status": "OK",
        "substitution_locked": False,
        "prescribed_product": {
            "product_id": product_id,
            "brand_name": brand_name,
            "manufacturer": manufacturer,
            "dosage_form": dosage_form,
            "normalized_strength": norm_strength,
            "canonical_generics": canonical_generics,
            "comparison_unit": prescribed_comp_unit,
            "normalized_unit_price_bdt": prescribed_price,
        },
        "alternatives_count": len(alternatives),
        "cheaper_alternatives_count": sum(1 for a in alternatives if a["is_cheaper"]),
        "alternatives": alternatives,
        "disclaimer": (
            "Decision-support prototype only; not clinical advice. Labelled strictly "
            "as 'same-generic alternative', NEVER as bioequivalent."
        ),
    }
