"""Fuzzy brand search and prescription item resolution using RapidFuzz and SQLite."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

from rapidfuzz import fuzz, process


def search_products(
    query: str,
    conn: sqlite3.Connection,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search catalog for brands and products matching query string using SQL prefix and RapidFuzz."""
    q_clean = query.strip()
    if not q_clean:
        return []

    cursor = conn.cursor()

    # 1. Exact / Prefix search
    cursor.execute(
        """
        SELECT p.product_id, p.raw_brand_name, p.dosage_form, p.normalized_strength,
               p.manufacturer, p.raw_generic
        FROM products p
        WHERE p.raw_brand_name LIKE ? OR p.slug LIKE ?
        LIMIT ?
        """,
        (f"{q_clean}%", f"{q_clean.lower()}%", limit),
    )
    direct_rows = cursor.fetchall()
    if direct_rows:
        return [
            {
                "product_id": r[0],
                "brand_name": r[1],
                "dosage_form": r[2],
                "normalized_strength": r[3],
                "manufacturer": r[4],
                "generic": r[5],
                "match_score": 100.0,
            }
            for r in direct_rows
        ]

    # 2. Fuzzy match over distinct brands
    cursor.execute("SELECT DISTINCT brand_name FROM brands")
    all_brands = [row[0] for row in cursor.fetchall()]

    matches = process.extract(
        q_clean,
        all_brands,
        scorer=fuzz.token_sort_ratio,
        limit=limit,
        score_cutoff=60.0,
    )

    results: List[Dict[str, Any]] = []
    for brand_matched, score, _ in matches:
        cursor.execute(
            """
            SELECT p.product_id, p.raw_brand_name, p.dosage_form, p.normalized_strength,
                   p.manufacturer, p.raw_generic
            FROM products p
            WHERE p.raw_brand_name = ?
            LIMIT 5
            """,
            (brand_matched,),
        )
        for r in cursor.fetchall():
            results.append({
                "product_id": r[0],
                "brand_name": r[1],
                "dosage_form": r[2],
                "normalized_strength": r[3],
                "manufacturer": r[4],
                "generic": r[5],
                "match_score": round(score, 2),
            })
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    return results


def resolve_prescribed_item(
    item_input: Union[int, str, Dict[str, Any]],
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Resolve a prescribed item input into a concrete SKU product record.

    If given a brand name that maps to multiple distinct SKUs (e.g. 'Napa' matching
    tablets, syrups, drops, and multiple strengths), returns resolution_status = 'AMBIGUOUS'
    with candidate SKUs, strictly avoiding silent arbitrary selection.
    """
    cursor = conn.cursor()

    # Case 1: Direct integer product_id
    if isinstance(item_input, int):
        target_id = item_input
        cursor.execute(
            """
            SELECT p.product_id, p.brand_id, p.raw_brand_name, p.dosage_form,
                   p.normalized_strength, p.release_type, p.manufacturer
            FROM products p
            WHERE p.product_id = ?
            """,
            (target_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {
                "resolution_status": "NOT_FOUND",
                "item_input": item_input,
                "explanation": f"Product ID {target_id} not found in catalog.",
            }

        # Fetch canonical generics
        cursor.execute(
            "SELECT canonical_generic FROM generic_components WHERE product_id = ? ORDER BY component_order",
            (target_id,),
        )
        generics = [g[0] for g in cursor.fetchall()]

        # Fetch numeric strength & unit
        cursor.execute(
            "SELECT numeric_value, canonical_unit FROM strength_components WHERE product_id = ? AND component_order = 1",
            (target_id,),
        )
        s_row = cursor.fetchone()
        num_val = s_row[0] if s_row else None
        s_unit = s_row[1] if s_row else None

        return {
            "resolution_status": "RESOLVED",
            "product_id": row[0],
            "brand_id": row[1],
            "brand_name": row[2],
            "dosage_form": row[3],
            "strength": row[4],
            "release_type": row[5],
            "manufacturer": row[6],
            "canonical_generics": generics,
            "numeric_strength": num_val,
            "strength_unit": s_unit,
            "generic_status": "OK" if generics else "UNVERIFIED",
            "strength_status": "OK" if num_val is not None else "UNVERIFIED",
        }

    # Case 2: Dict input with product_id
    if isinstance(item_input, dict) and "product_id" in item_input and item_input["product_id"]:
        return resolve_prescribed_item(int(item_input["product_id"]), conn)

    # Case 3: Text query or dict with brand_name
    query_name = item_input if isinstance(item_input, str) else item_input.get("brand_name", "")
    desired_form = item_input.get("dosage_form") if isinstance(item_input, dict) else None
    desired_str = item_input.get("strength") if isinstance(item_input, dict) else None

    # Query matching products
    sql = "SELECT p.product_id, p.raw_brand_name, p.dosage_form, p.normalized_strength, p.manufacturer FROM products p WHERE LOWER(p.raw_brand_name) = LOWER(?)"
    params = [query_name.strip()]

    if desired_form:
        sql += " AND LOWER(p.dosage_form) = LOWER(?)"
        params.append(desired_form.strip())
    if desired_str:
        sql += " AND (LOWER(p.normalized_strength) = LOWER(?) OR LOWER(p.raw_strength) = LOWER(?))"
        params.extend([desired_str.strip(), desired_str.strip()])

    cursor.execute(sql, params)
    matches = cursor.fetchall()

    if len(matches) == 1:
        # Exact unambiguous resolution!
        return resolve_prescribed_item(matches[0][0], conn)
    elif len(matches) > 1:
        candidates = [
            {
                "product_id": m[0],
                "brand_name": m[1],
                "dosage_form": m[2],
                "strength": m[3],
                "manufacturer": m[4],
            }
            for m in matches
        ]
        return {
            "resolution_status": "AMBIGUOUS",
            "query": query_name,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "explanation": (
                f"Brand '{query_name}' matches {len(candidates)} distinct SKU presentations in catalog. "
                f"Please specify dosage_form, strength, or explicit product_id to resolve."
            ),
        }
    else:
        # Try fuzzy search
        fuzzy_results = search_products(query_name, conn, limit=5)
        return {
            "resolution_status": "NOT_FOUND",
            "query": query_name,
            "explanation": f"Brand name '{query_name}' was not found in catalog.",
            "suggestions": fuzzy_results,
        }
