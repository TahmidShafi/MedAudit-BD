"""Prescription audit engine integrating duplicate, release-hazard, shelf-hazard, NTI, and alternative checks."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from medaudit.audit.alternatives import find_same_generic_alternatives
from medaudit.audit.duplicates import check_duplicate_active_ingredients
from medaudit.audit.nti import get_nti_badge, is_nti_generic
from medaudit.audit.release_type import (
    check_catalog_shelf_10x_hazards,
    check_intra_prescription_release_and_strength_hazards,
)
from medaudit.audit.search import resolve_prescribed_item
from medaudit.config import PROJECT_ROOT

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "processed" / "medaudit.db"

DISCLAIMER_TEXT = (
    "Decision-support prototype only; not clinical advice and not a medical device. "
    "All alternatives are labelled strictly as 'same-generic alternative', never as bioequivalent."
)


def audit_prescription(
    items: List[Union[int, str, Dict[str, Any]]],
    conn: Optional[sqlite3.Connection] = None,
    db_path: Path = DEFAULT_DB_PATH,
    manufacturer_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute complete prescription audit over 2 to 8 prescribed pharmaceutical items.

    Audits:
    1. Item resolution: Resolves product IDs or flags AMBIGUOUS brand matches.
    2. Duplicate active ingredients (single, compound, single-vs-compound).
    3. Intra-prescription release kinetics & 10x dose difference hazards.
    4. Catalog 10x shelf look-alike packaging hazards.
    5. NTI classification and brand substitution locking.
    6. Cheaper same-generic alternative ranking across all items.

    Returns:
        Structured audit dictionary with overall status, per-check outcomes, and mandatory disclaimer.
    """
    should_close = False
    if conn is None:
        conn = sqlite3.connect(db_path)
        should_close = True

    try:
        # Step 1: Resolve all prescribed items
        resolved_items: List[Dict[str, Any]] = []
        ambiguous_items: List[Dict[str, Any]] = []
        unresolved_items: List[Dict[str, Any]] = []

        for item_input in items:
            res = resolve_prescribed_item(item_input, conn)
            status = res.get("resolution_status")
            if status == "RESOLVED":
                resolved_items.append(res)
            elif status == "AMBIGUOUS":
                ambiguous_items.append(res)
            else:
                unresolved_items.append(res)

        if ambiguous_items or unresolved_items:
            return {
                "overall_status": "AMBIGUOUS_OR_UNRESOLVED",
                "disclaimer": DISCLAIMER_TEXT,
                "ambiguous_items": ambiguous_items,
                "unresolved_items": unresolved_items,
                "resolved_count": len(resolved_items),
                "explanation": (
                    "One or more prescription items could not be unambiguously resolved to a specific "
                    "catalog SKU. Please select a specific presentation from the candidate list."
                ),
            }

        # Step 2: Check Duplicate Active Ingredients
        dup_result = check_duplicate_active_ingredients(resolved_items)

        # Step 3: Check Intra-Prescription Release & 10x Strength Hazards
        release_hazards = check_intra_prescription_release_and_strength_hazards(resolved_items)

        # Step 4: Check Catalog Shelf 10x Hazards for each item
        shelf_hazards = []
        for it in resolved_items:
            sh = check_catalog_shelf_10x_hazards(it["product_id"], conn)
            if sh.get("hazards"):
                shelf_hazards.extend(sh["hazards"])

        # Step 5: Check NTI and Cheaper Alternatives for each item
        item_audits: List[Dict[str, Any]] = []
        any_nti_flag = False

        for it in resolved_items:
            p_id = it["product_id"]
            generics = it.get("canonical_generics", [])

            # Check NTI status
            nti_badges = []
            for g in generics:
                badge = get_nti_badge(g)
                if badge:
                    nti_badges.append(badge)
                    any_nti_flag = True

            # Find cheaper alternatives
            alt_res = find_same_generic_alternatives(
                p_id, conn, manufacturer_filter=manufacturer_filter, limit=5
            )

            item_audits.append({
                "product_id": p_id,
                "brand_name": it["brand_name"],
                "dosage_form": it["dosage_form"],
                "strength": it["strength"],
                "release_type": it.get("release_type", "IR"),
                "canonical_generics": generics,
                "is_nti": bool(nti_badges),
                "nti_details": nti_badges,
                "alternatives_status": alt_res["status"],
                "substitution_locked": alt_res["substitution_locked"],
                "alternatives_count": alt_res.get("alternatives_count", 0),
                "cheaper_alternatives_count": alt_res.get("cheaper_alternatives_count", 0),
                "top_alternatives": alt_res.get("alternatives", []),
            })

        # Collate Overall Status
        has_flags = (
            dup_result["status"] == "FLAG"
            or any(h.get("status") == "FLAG" for h in release_hazards)
            or bool(shelf_hazards)
            or any_nti_flag
        )
        has_unverified = (
            dup_result["status"] == "UNVERIFIED"
            or any(h.get("status") == "UNVERIFIED" for h in release_hazards)
            or any(it["alternatives_status"] == "UNVERIFIED" for it in item_audits)
        )

        if has_flags:
            overall_status = "FLAG"
        elif has_unverified:
            overall_status = "UNVERIFIED"
        else:
            overall_status = "OK"

        return {
            "overall_status": overall_status,
            "disclaimer": DISCLAIMER_TEXT,
            "item_count": len(resolved_items),
            "duplicate_check": dup_result,
            "intra_prescription_hazards": release_hazards,
            "shelf_lookalike_hazards": shelf_hazards,
            "items": item_audits,
        }

    finally:
        if should_close:
            conn.close()
