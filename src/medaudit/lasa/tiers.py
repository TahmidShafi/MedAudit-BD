"""Two-Tier LASA Evaluation, Diff Previews, and Database Persistence.

Evaluates look-alike sound-alike drug pairs across 14,013 deduplicated brands:
- Tier 1 (Cross-Manufacturer): Compares full normalized brand names.
- Tier 2 (Same-Manufacturer): Compares post-prefix stems with configurable minimum stem length.
- Generic overlap classification: 'same-generic pair (lower priority)' vs 'different-generic lexical warning'.
"""

from __future__ import annotations

import difflib
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from rapidfuzz.distance import DamerauLevenshtein

from medaudit.lasa.candidates import (
    BrandCandidate,
    compute_blocked_candidates,
    compute_full_similarity_matrix,
    load_brand_candidates,
)

LASA_DISCLAIMER = "lexical similarity warning, not clinically validated"
DIFF_PREVIEW_DISCLAIMER = "visual aid, not validated"


@dataclass(frozen=True)
class LASAPair:
    """Precomputed LASA pair entity corresponding to SQLite lasa_pairs row."""

    brand_id_a: int
    brand_id_b: int
    tier: int
    edit_similarity: float
    phonetic_match: int
    same_generic: int
    same_manufacturer: int
    diff_preview: str


def generate_diff_preview(s1: str, s2: str) -> str:
    """Generate pairwise character diff preview string highlighting differing character blocks.

    Explicitly labelled 'visual aid, not validated'. Does not claim clinical Tall-Man lettering effectiveness.
    """
    matcher = difflib.SequenceMatcher(None, s1.lower(), s2.lower())
    diff1, diff2 = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            diff1.append(s1[i1:i2])
            diff2.append(s2[j1:j2])
        else:
            part1 = s1[i1:i2]
            part2 = s2[j1:j2]
            if part1:
                diff1.append(f"[{part1}]")
            if part2:
                diff2.append(f"[{part2}]")
    d1_str = "".join(diff1)
    d2_str = "".join(diff2)
    return f"{d1_str} vs {d2_str} ({DIFF_PREVIEW_DISCLAIMER})"


def classify_generic_overlap(
    generics_a: frozenset[str], generics_b: frozenset[str]
) -> Tuple[int, str]:
    """Classify whether two brands share the exact same canonical generic active ingredients.

    Returns:
        Tuple of (same_generic_flag: int, clinical_label: str).
    """
    if generics_a and generics_a == generics_b:
        return 1, "same-generic pair (lower priority)"
    return 0, "different-generic lexical warning"


def compute_lasa_pairs(
    candidates: List[BrandCandidate],
    threshold: float = 0.80,
    phonetic_threshold: float = 0.70,
    min_stem_length: int = 4,
    similarity_matrix: Optional[np.ndarray] = None,
    use_length_blocking: bool = True,
) -> Tuple[List[LASAPair], Dict[str, Any]]:
    """Compute complete 2-tier LASA pairs across all candidate brands.

    Rules:
    - Tier 1 (Cross-Manufacturer): manufacturer_a != manufacturer_b. Compares full normalized_brand_name.
      Flags if edit_similarity >= threshold OR (edit_similarity >= phonetic_threshold AND phonetic_match == 1).
    - Tier 2 (Same-Manufacturer): manufacturer_a == manufacturer_b. Compares post-prefix stem if a shared
      manufacturer prefix was stripped, or full name otherwise. Enforces min_stem_length.
      Flags if edit_similarity >= threshold OR (edit_similarity >= phonetic_threshold AND phonetic_match == 1).

    Memory Efficiency:
    - When similarity_matrix is None and use_length_blocking is True, uses length-blocked cdist
      (53.88 MB peak RAM, 100% recall) instead of allocating a 749 MB dense similarity matrix.

    Returns:
        Tuple of (list_of_lasa_pairs, statistics_dict).
    """
    n = len(candidates)
    tier1_pairs: List[LASAPair] = []
    exact_collisions_count = 0

    # 1. Tier 1: Cross-Manufacturer Evaluation
    if similarity_matrix is not None:
        rows, cols = np.where(
            (similarity_matrix >= phonetic_threshold)
            & (np.triu(np.ones((n, n), dtype=bool), k=1))
        )
        candidate_iter = (
            (r, c, float(similarity_matrix[r, c])) for r, c in zip(rows, cols)
        )
    elif use_length_blocking:
        names = [b.normalized_brand_name for b in candidates]
        candidate_iter = compute_blocked_candidates(
            names, min_similarity=phonetic_threshold, block_mode="length"
        )
    else:
        names = [b.normalized_brand_name for b in candidates]
        similarity_matrix = compute_full_similarity_matrix(names)
        rows, cols = np.where(
            (similarity_matrix >= phonetic_threshold)
            & (np.triu(np.ones((n, n), dtype=bool), k=1))
        )
        candidate_iter = (
            (r, c, float(similarity_matrix[r, c])) for r, c in zip(rows, cols)
        )

    for r, c, sim in candidate_iter:
        b1 = candidates[r]
        b2 = candidates[c]

        # Only cross-manufacturer pairs in Tier 1
        if b1.manufacturer == b2.manufacturer:
            continue

        phon_match = 1 if (b1.phonetic_key and b1.phonetic_key == b2.phonetic_key) else 0

        # Flag rule: sim >= threshold OR (sim >= phonetic_threshold AND phonetic_match)
        if sim >= threshold or (sim >= phonetic_threshold and phon_match == 1):
            if sim == 1.0:
                exact_collisions_count += 1

            same_gen, _ = classify_generic_overlap(b1.canonical_generics, b2.canonical_generics)
            diff_str = generate_diff_preview(b1.brand_name, b2.brand_name)

            bid_a, bid_b = (b1.brand_id, b2.brand_id) if b1.brand_id < b2.brand_id else (b2.brand_id, b1.brand_id)
            tier1_pairs.append(
                LASAPair(
                    brand_id_a=bid_a,
                    brand_id_b=bid_b,
                    tier=1,
                    edit_similarity=round(sim, 4),
                    phonetic_match=phon_match,
                    same_generic=same_gen,
                    same_manufacturer=0,
                    diff_preview=diff_str,
                )
            )

    # 2. Tier 2: Same-Manufacturer Evaluation
    mfg_groups: Dict[str, List[int]] = defaultdict(list)
    for idx, b in enumerate(candidates):
        mfg_groups[b.manufacturer].append(idx)

    tier2_pairs: List[LASAPair] = []
    for _, indices in mfg_groups.items():
        if len(indices) < 2:
            continue
        for i_idx in range(len(indices)):
            for j_idx in range(i_idx + 1, len(indices)):
                b1 = candidates[indices[i_idx]]
                b2 = candidates[indices[j_idx]]

                # If both share a house prefix, compare post-prefix stems
                if b1.prefix and b2.prefix and b1.prefix == b2.prefix:
                    s1 = b1.prefix_stem
                    s2 = b2.prefix_stem
                    ph1 = b1.stem_phonetic_key
                    ph2 = b2.stem_phonetic_key
                else:
                    s1 = b1.normalized_brand_name
                    s2 = b2.normalized_brand_name
                    ph1 = b1.phonetic_key
                    ph2 = b2.phonetic_key

                # Enforce min_stem_length threshold
                if len(s1) < min_stem_length or len(s2) < min_stem_length:
                    continue

                sim = DamerauLevenshtein.normalized_similarity(s1, s2)
                phon_match = 1 if (ph1 and ph1 == ph2) else 0

                if sim >= threshold or (sim >= phonetic_threshold and phon_match == 1):
                    same_gen, _ = classify_generic_overlap(
                        b1.canonical_generics, b2.canonical_generics
                    )
                    diff_str = generate_diff_preview(b1.brand_name, b2.brand_name)
                    bid_a, bid_b = (b1.brand_id, b2.brand_id) if b1.brand_id < b2.brand_id else (b2.brand_id, b1.brand_id)
                    tier2_pairs.append(
                        LASAPair(
                            brand_id_a=bid_a,
                            brand_id_b=bid_b,
                            tier=2,
                            edit_similarity=round(sim, 4),
                            phonetic_match=phon_match,
                            same_generic=same_gen,
                            same_manufacturer=1,
                            diff_preview=diff_str,
                        )
                    )

    all_pairs = tier1_pairs + tier2_pairs
    same_gen_count = sum(1 for p in all_pairs if p.same_generic == 1)
    diff_gen_count = sum(1 for p in all_pairs if p.same_generic == 0)

    stats = {
        "total_pairs": len(all_pairs),
        "tier1_count": len(tier1_pairs),
        "tier2_count": len(tier2_pairs),
        "exact_collisions_count": exact_collisions_count,
        "same_generic_count": same_gen_count,
        "different_generic_count": diff_gen_count,
        "threshold": threshold,
        "phonetic_threshold": phonetic_threshold,
        "min_stem_length": min_stem_length,
    }

    return all_pairs, stats


def save_lasa_pairs_to_db(pairs: List[LASAPair], conn: sqlite3.Connection) -> int:
    """Persist precomputed LASA pairs into SQLite lasa_pairs table.

    Args:
        pairs: List of LASAPair records.
        conn: Open SQLite database connection.

    Returns:
        Number of rows inserted.
    """
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lasa_pairs")

    rows = [
        (
            p.brand_id_a,
            p.brand_id_b,
            p.tier,
            p.edit_similarity,
            p.phonetic_match,
            p.same_generic,
            p.same_manufacturer,
            p.diff_preview,
        )
        for p in pairs
    ]

    cursor.executemany(
        """
        INSERT OR REPLACE INTO lasa_pairs (
            brand_id_a, brand_id_b, tier, edit_similarity, phonetic_match,
            same_generic, same_manufacturer, diff_preview
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def get_lasa_warnings_for_brand(
    brand_id: int,
    conn: sqlite3.Connection,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Retrieve precomputed LASA warnings for a specific brand from SQLite.

    Returns structured warnings with clinical disclaimer and generic priority labels.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            lp.brand_id_a, lp.brand_id_b, lp.tier, lp.edit_similarity,
            lp.phonetic_match, lp.same_generic, lp.same_manufacturer, lp.diff_preview,
            b_other.brand_name AS other_brand_name,
            b_other.manufacturer AS other_manufacturer
        FROM lasa_pairs lp
        JOIN brands b_other ON (
            CASE WHEN lp.brand_id_a = ? THEN lp.brand_id_b ELSE lp.brand_id_a END = b_other.brand_id
        )
        WHERE lp.brand_id_a = ? OR lp.brand_id_b = ?
        ORDER BY lp.tier ASC, lp.edit_similarity DESC
        LIMIT ?
        """,
        (brand_id, brand_id, brand_id, limit),
    )
    rows = cursor.fetchall()

    warnings = []
    for r in rows:
        same_gen = bool(r[5])
        priority_label = (
            "same-generic pair (lower priority)"
            if same_gen
            else "different-generic lexical warning"
        )

        warnings.append(
            {
                "confused_brand_name": r[8],
                "confused_manufacturer": r[9],
                "tier": r[2],
                "tier_name": "Tier 1 (Cross-Manufacturer)" if r[2] == 1 else "Tier 2 (Same-Manufacturer)",
                "edit_similarity": r[3],
                "phonetic_match": bool(r[4]),
                "same_generic": same_gen,
                "generic_priority_label": priority_label,
                "diff_preview": r[7],
                "disclaimer": LASA_DISCLAIMER,
            }
        )

    return warnings


def check_intra_prescription_lasa_hazards(
    brand_ids: List[int],
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    """Detect if any pair of items in the prescription match an active LASA pair."""
    if len(brand_ids) < 2:
        return []

    cursor = conn.cursor()
    hazards = []
    unique_bids = sorted(set(brand_ids))

    for i in range(len(unique_bids)):
        for j in range(i + 1, len(unique_bids)):
            bid_a, bid_b = unique_bids[i], unique_bids[j]
            cursor.execute(
                """
                SELECT
                    lp.tier, lp.edit_similarity, lp.phonetic_match,
                    lp.same_generic, lp.diff_preview,
                    b1.brand_name, b1.manufacturer,
                    b2.brand_name, b2.manufacturer
                FROM lasa_pairs lp
                JOIN brands b1 ON lp.brand_id_a = b1.brand_id
                JOIN brands b2 ON lp.brand_id_b = b2.brand_id
                WHERE (lp.brand_id_a = ? AND lp.brand_id_b = ?)
                   OR (lp.brand_id_a = ? AND lp.brand_id_b = ?)
                """,
                (bid_a, bid_b, bid_b, bid_a),
            )
            row = cursor.fetchone()
            if row:
                same_gen = bool(row[3])
                label = (
                    "same-generic pair (lower priority)"
                    if same_gen
                    else "different-generic lexical warning"
                )
                hazards.append(
                    {
                        "brand_id_a": bid_a,
                        "brand_id_b": bid_b,
                        "brand_name_a": row[5],
                        "manufacturer_a": row[6],
                        "brand_name_b": row[7],
                        "manufacturer_b": row[8],
                        "tier": row[0],
                        "edit_similarity": row[1],
                        "phonetic_match": bool(row[2]),
                        "same_generic": same_gen,
                        "priority_label": label,
                        "diff_preview": row[4],
                        "disclaimer": LASA_DISCLAIMER,
                        "status": "FLAG",
                    }
                )

    return hazards
