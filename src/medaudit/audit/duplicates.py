"""Duplicate active ingredient detection across single and compound generic prescriptions."""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple


def check_duplicate_active_ingredients(
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Detect overlapping active ingredients across 2 to 8 prescribed items.

    Flags any canonical generic appearing in >=2 items, including:
    - Single vs Single (e.g. Paracetamol + Paracetamol)
    - Single vs Compound (e.g. Paracetamol + Paracetamol + Caffeine)
    - Compound vs Compound (e.g. Paracetamol + Tramadol + Paracetamol + Caffeine)

    Returns:
        Dict with overall check status ('OK', 'FLAG', 'UNVERIFIED'), detected duplicate groups,
        and per-item audit outcomes.
    """
    generic_to_items: Dict[str, List[Dict[str, Any]]] = {}
    has_unverified_item = False
    unverified_reasons: List[str] = []

    for item in items:
        p_id = item.get("product_id")
        brand_name = item.get("brand_name", f"Product #{p_id}")
        generics = item.get("canonical_generics", [])
        status = item.get("generic_status", "OK")

        if status == "UNVERIFIED" or not generics:
            has_unverified_item = True
            unverified_reasons.append(
                f"Item '{brand_name}' has unparsed or missing generic formulation (MISSING_GENERIC)"
            )
            continue

        for gen in generics:
            gen_clean = gen.strip().lower()
            if gen_clean not in generic_to_items:
                generic_to_items[gen_clean] = []
            generic_to_items[gen_clean].append({
                "product_id": p_id,
                "brand_name": brand_name,
                "dosage_form": item.get("dosage_form"),
                "strength": item.get("strength"),
                "is_compound": len(generics) > 1,
            })

    duplicate_flags: List[Dict[str, Any]] = []
    for gen, matching_items in sorted(generic_to_items.items()):
        if len(matching_items) >= 2:
            duplicate_flags.append({
                "canonical_generic": gen,
                "occurrence_count": len(matching_items),
                "prescribed_items": matching_items,
                "hazard_type": "DUPLICATE_ACTIVE_INGREDIENT",
                "explanation": (
                    f"Active ingredient '{gen}' is co-prescribed across {len(matching_items)} items: "
                    f"{', '.join(i['brand_name'] for i in matching_items)}. "
                    f"Exposes patient to unintended cumulative dose toxicity."
                ),
            })

    if duplicate_flags:
        overall_status = "FLAG"
    elif has_unverified_item:
        overall_status = "UNVERIFIED"
    else:
        overall_status = "OK"

    return {
        "status": overall_status,
        "duplicate_count": len(duplicate_flags),
        "duplicates": duplicate_flags,
        "unverified_reasons": unverified_reasons,
    }
