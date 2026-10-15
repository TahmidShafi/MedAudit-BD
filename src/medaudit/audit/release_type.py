"""Release type classification, intra-prescription hazards, and 10x shelf look-alike detection."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

RELEASE_MODIFIERS: List[str] = [
    "XR",
    "SR",
    "CR",
    "MR",
    "ER",
    "OD",
    "LA",
    "Retard",
    "Contin",
    "EC",
]


def detect_release_type(brand_name: str, dosage_form: Optional[str] = None) -> str:
    """Detect pharmaceutical release modifier from brand name and dosage form.

    Defaults to 'IR' (Immediate Release) for standard oral solids and other formulations.
    """
    text = f"{brand_name} {dosage_form or ''}"
    for tag in RELEASE_MODIFIERS:
        if re.search(r"\b" + tag + r"\b", text, re.IGNORECASE):
            return tag.upper()
    lower = text.lower()
    if "enteric" in lower:
        return "EC"
    if "sustained" in lower:
        return "SR"
    if "extended" in lower:
        return "XR"
    if "controlled" in lower:
        return "CR"
    if "modified" in lower:
        return "MR"
    if "retard" in lower:
        return "RETARD"
    if "contin" in lower:
        return "CONTIN"
    return "IR"


def check_intra_prescription_release_and_strength_hazards(
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Flag intra-prescription hazards where co-prescribed items share a generic and:
    1. Differ in release type (e.g. IR vs XR/SR/CR), or
    2. Have single-component strengths differing by >= 10x or <= 0.1x.
    """
    hazards: List[Dict[str, Any]] = []
    n = len(items)

    for i in range(n):
        for j in range(i + 1, n):
            item_a = items[i]
            item_b = items[j]

            # Compare generics
            generics_a = set(item_a.get("canonical_generics", []))
            generics_b = set(item_b.get("canonical_generics", []))
            common = generics_a & generics_b

            if not common:
                continue

            # Check 1: Release type mismatch (e.g. IR vs XR)
            rel_a = item_a.get("release_type", "IR")
            rel_b = item_b.get("release_type", "IR")
            if rel_a != rel_b:
                hazards.append({
                    "hazard_type": "RELEASE_TYPE_MISMATCH",
                    "status": "FLAG",
                    "shared_generic": sorted(list(common)),
                    "item_a": {
                        "product_id": item_a.get("product_id"),
                        "brand_name": item_a.get("brand_name"),
                        "release_type": rel_a,
                    },
                    "item_b": {
                        "product_id": item_b.get("product_id"),
                        "brand_name": item_b.get("brand_name"),
                        "release_type": rel_b,
                    },
                    "explanation": (
                        f"Items '{item_a.get('brand_name')}' ({rel_a}) and '{item_b.get('brand_name')}' ({rel_b}) "
                        f"share generic {sorted(list(common))} but have conflicting release kinetics."
                    ),
                })

            # Check 2: 10x strength difference within single-ingredient matches
            val_a = item_a.get("numeric_strength")
            unit_a = item_a.get("strength_unit")
            val_b = item_b.get("numeric_strength")
            unit_b = item_b.get("strength_unit")

            # Check if strength check is unverified
            if item_a.get("strength_status") == "UNVERIFIED" or item_b.get("strength_status") == "UNVERIFIED":
                hazards.append({
                    "hazard_type": "10X_STRENGTH_INTRA_PRESCRIPTION",
                    "status": "UNVERIFIED",
                    "shared_generic": sorted(list(common)),
                    "explanation": "Unable to verify 10x strength ratio due to unparsed/missing strength specification.",
                })
            elif val_a is not None and val_b is not None and unit_a == unit_b and val_a > 0 and val_b > 0:
                ratio = val_a / val_b
                if ratio >= 10.0 or ratio <= 0.1:
                    hazards.append({
                        "hazard_type": "10X_STRENGTH_INTRA_PRESCRIPTION",
                        "status": "FLAG",
                        "shared_generic": sorted(list(common)),
                        "item_a": {
                            "product_id": item_a.get("product_id"),
                            "brand_name": item_a.get("brand_name"),
                            "strength": f"{val_a} {unit_a}",
                        },
                        "item_b": {
                            "product_id": item_b.get("product_id"),
                            "brand_name": item_b.get("brand_name"),
                            "strength": f"{val_b} {unit_b}",
                        },
                        "ratio": round(ratio if ratio >= 1.0 else 1.0 / ratio, 2),
                        "explanation": (
                            f"Items '{item_a.get('brand_name')}' ({val_a} {unit_a}) and '{item_b.get('brand_name')}' "
                            f"({val_b} {unit_b}) share generic {sorted(list(common))} with a 10x or greater "
                            f"dose differential ({ratio:.1f}x), posing high toxicity or under-dosing hazard."
                        ),
                    })

    return hazards


def check_catalog_shelf_10x_hazards(
    product_id: int,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Check if the same brand_id and dosage_form has a sibling SKU in the catalog
    whose numeric strength is exactly 10x (or 0.1x) the prescribed strength.
    """
    cursor = conn.cursor()

    # Fetch product brand_id, dosage_form, and strength
    cursor.execute(
        """
        SELECT p.brand_id, p.raw_brand_name, p.dosage_form, sc.numeric_value, sc.canonical_unit
        FROM products p
        LEFT JOIN strength_components sc ON p.product_id = sc.product_id AND sc.component_order = 1
        WHERE p.product_id = ?
        """,
        (product_id,),
    )
    row = cursor.fetchone()
    if not row:
        return {"status": "UNVERIFIED", "hazards": [], "details": f"Product ID {product_id} not found"}

    brand_id, brand_name, dosage_form, num_val, unit = row

    if num_val is None or not unit:
        return {
            "status": "UNVERIFIED",
            "hazards": [],
            "details": "Prescribed product has unparsed or missing strength in database",
        }

    # Query sibling SKUs under the same brand_id and dosage_form
    cursor.execute(
        """
        SELECT p.product_id, p.raw_brand_name, sc.numeric_value, sc.canonical_unit
        FROM products p
        JOIN strength_components sc ON p.product_id = sc.product_id AND sc.component_order = 1
        WHERE p.brand_id = ? AND p.dosage_form = ? AND p.product_id != ?
        """,
        (brand_id, dosage_form, product_id),
    )
    siblings = cursor.fetchall()

    hazards = []
    target_10x = round(num_val * 10.0, 4)
    target_point_1x = round(num_val * 0.1, 4)

    for sib_id, sib_brand, sib_val, sib_unit in siblings:
        if sib_val is not None and sib_unit == unit:
            rounded_sib = round(sib_val, 4)
            if abs(rounded_sib - target_10x) < 0.001 or abs(rounded_sib - target_point_1x) < 0.001:
                ratio = 10.0 if rounded_sib >= num_val else 0.1
                hazards.append({
                    "sibling_product_id": sib_id,
                    "sibling_brand_name": sib_brand,
                    "prescribed_strength": f"{num_val} {unit}",
                    "sibling_strength": f"{sib_val} {sib_unit}",
                    "ratio": f"{ratio}x",
                    "hazard_badge": "CATALOG_10X_LOOKALIKE_SHELF_HAZARD",
                    "explanation": (
                        f"Sibling SKU '{sib_brand}' ({sib_val} {sib_unit}) exists on the shelf under the exact same "
                        f"brand and dosage form ({dosage_form}) at a 10x dose multiple, creating severe packaging confusion risk."
                    ),
                })

    status = "FLAG" if hazards else "OK"
    return {
        "status": status,
        "product_id": product_id,
        "brand_name": brand_name,
        "dosage_form": dosage_form,
        "strength": f"{num_val} {unit}",
        "hazards": hazards,
    }
