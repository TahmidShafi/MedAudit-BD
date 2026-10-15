"""Unit tests for MedAudit BD Look-Alike Sound-Alike (LASA) module.

Tests deterministic pharmaceutical phonetic canonicalization, prefix stem extraction,
Tier 1 vs Tier 2 evaluation, exact cross-manufacturer collisions, diff previews,
and SQLite query helpers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from rapidfuzz.distance import DamerauLevenshtein

from medaudit.audit.engine import audit_prescription
from medaudit.config import PROJECT_ROOT
from medaudit.lasa.candidates import (
    BrandCandidate,
    extract_prefix_and_stem,
    load_brand_candidates,
)
from medaudit.lasa.phonetic import pharma_phonetic
from medaudit.lasa.tiers import (
    DIFF_PREVIEW_DISCLAIMER,
    LASA_DISCLAIMER,
    check_intra_prescription_lasa_hazards,
    classify_generic_overlap,
    compute_lasa_pairs,
    generate_diff_preview,
    get_lasa_warnings_for_brand,
)

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "processed" / "medaudit.db"


# ============================================================================
# 1. Phonetic Canonicalizer Tests
# ============================================================================

def test_pharma_phonetic_no_soundex_truncation():
    """Phonetic key must not truncate to 4 characters like Soundex."""
    key = pharma_phonetic("chlorpromazine")
    assert key == "klrprmzn"
    assert len(key) > 4


def test_pharma_phonetic_digraphs_and_substitutions():
    """Verify standard pharmaceutical digraphs and consonant normalizations."""
    # ph -> f
    assert pharma_phonetic("phenobarbital").startswith("f")
    assert "ph" not in pharma_phonetic("phenobarbital")

    # ch -> k
    assert pharma_phonetic("chlorpromazine") == pharma_phonetic("klorpromazine")

    # c before e, i, y -> s
    assert pharma_phonetic("cefixime").startswith("s")
    assert pharma_phonetic("ciprofloxacin").startswith("s")

    # c before a, o, u -> k
    assert pharma_phonetic("cloxacillin").startswith("k")
    assert pharma_phonetic("carbamazepine").startswith("k")

    # q -> k, x -> z, y -> i
    assert pharma_phonetic("quick") == "k"
    assert pharma_phonetic("xanax") == "znz"


def test_pharma_phonetic_silent_h():
    """Silent h after consonants must be dropped."""
    assert pharma_phonetic("rhinitis") == pharma_phonetic("rinitis")
    assert pharma_phonetic("therapy") == "trp"
    assert pharma_phonetic("ghrelin") == "grln"


def test_pharma_phonetic_vowel_stripping():
    """All vowels except the first character must be stripped."""
    assert pharma_phonetic("amiodarone") == "amdrn"
    assert pharma_phonetic("amlodipine") == "amldpn"
    assert pharma_phonetic("ephedrine") == "efdrn"


def test_pharma_phonetic_edge_cases():
    """Empty strings, non-alphabetic characters, and single letters."""
    assert pharma_phonetic("") == ""
    assert pharma_phonetic("123-456") == ""
    assert pharma_phonetic("A") == "a"
    assert pharma_phonetic("  Napa-500  ") == "np"


# ============================================================================
# 2. Prefix Stem Extraction Tests
# ============================================================================

def test_extract_prefix_and_stem():
    """Verify single-letter and multi-letter hyphenated prefix extraction."""
    # Single-letter house prefix
    p, s = extract_prefix_and_stem("G-Amoxicillin")
    assert p == "G"
    assert s == "amoxicillin"

    p, s = extract_prefix_and_stem("A-Clox")
    assert p == "A"
    assert s == "clox"

    # Multi-letter house prefix
    p, s = extract_prefix_and_stem("SB-Metformin")
    assert p == "SB"
    assert s == "metformin"

    # No hyphen / standard brand
    p, s = extract_prefix_and_stem("Napa")
    assert p is None
    assert s == "napa"

    # Case normalization
    p, s = extract_prefix_and_stem("g-amoxicillin")
    assert p == "G"
    assert s == "amoxicillin"


# ============================================================================
# 3. Diff Preview & Disclaimer Tests
# ============================================================================

def test_diff_preview_formatting():
    """Diff preview must bracket differences and include mandatory disclaimer."""
    diff = generate_diff_preview("napa", "napo")
    assert "nap[a] vs nap[o]" in diff
    assert DIFF_PREVIEW_DISCLAIMER in diff
    assert "visual aid, not validated" in diff


def test_generic_overlap_classification():
    """Check clinical safety framing labels for generic overlap."""
    same_gen_flag, label = classify_generic_overlap(
        frozenset(["paracetamol"]), frozenset(["paracetamol"])
    )
    assert same_gen_flag == 1
    assert label == "same-generic pair (lower priority)"
    assert "safe" not in label.lower()
    assert "bioequivalent" not in label.lower()

    diff_gen_flag, label2 = classify_generic_overlap(
        frozenset(["paracetamol"]), frozenset(["ibuprofen"])
    )
    assert diff_gen_flag == 0
    assert label2 == "different-generic lexical warning"


# ============================================================================
# 4. Tier 1 vs Tier 2 LASA Logic Tests
# ============================================================================

def test_tier1_cross_mfg_and_exact_collisions():
    """Tier 1 must compare full strings across different manufacturers and flag exact collisions."""
    candidates = [
        BrandCandidate(
            brand_id=1,
            brand_name="Napa",
            normalized_brand_name="napa",
            manufacturer="Beximco Pharmaceuticals Ltd.",
            prefix=None,
            prefix_stem="napa",
            phonetic_key=pharma_phonetic("napa"),
            stem_phonetic_key=pharma_phonetic("napa"),
            canonical_generics=frozenset(["paracetamol"]),
        ),
        BrandCandidate(
            brand_id=2,
            brand_name="Napa",
            normalized_brand_name="napa",
            manufacturer="Square Pharmaceuticals Ltd.",
            prefix=None,
            prefix_stem="napa",
            phonetic_key=pharma_phonetic("napa"),
            stem_phonetic_key=pharma_phonetic("napa"),
            canonical_generics=frozenset(["paracetamol"]),
        ),
        BrandCandidate(
            brand_id=3,
            brand_name="Napo",
            normalized_brand_name="napo",
            manufacturer="ACME Laboratories Ltd.",
            prefix=None,
            prefix_stem="napo",
            phonetic_key=pharma_phonetic("napo"),
            stem_phonetic_key=pharma_phonetic("napo"),
            canonical_generics=frozenset(["naproxen"]),
        ),
    ]

    pairs, stats = compute_lasa_pairs(candidates)
    assert stats["tier1_count"] >= 2
    assert stats["exact_collisions_count"] == 1  # Napa vs Napa

    # Find exact collision pair
    exact = [p for p in pairs if p.edit_similarity == 1.0]
    assert len(exact) == 1
    assert exact[0].tier == 1
    assert exact[0].same_generic == 1


def test_tier2_same_mfg_min_stem_length():
    """Tier 2 must strip shared prefixes and skip stems shorter than min_stem_length."""
    candidates = [
        # Pair with stem length < 4 (skipped in Tier 2)
        BrandCandidate(
            brand_id=10,
            brand_name="3-C",
            normalized_brand_name="3-c",
            manufacturer="Edruc Limited",
            prefix="3",
            prefix_stem="c",
            phonetic_key=pharma_phonetic("3-c"),
            stem_phonetic_key=pharma_phonetic("c"),
            canonical_generics=frozenset(["ascorbic acid"]),
        ),
        BrandCandidate(
            brand_id=11,
            brand_name="3-F",
            normalized_brand_name="3-f",
            manufacturer="Edruc Limited",
            prefix="3",
            prefix_stem="f",
            phonetic_key=pharma_phonetic("3-f"),
            stem_phonetic_key=pharma_phonetic("f"),
            canonical_generics=frozenset(["folic acid"]),
        ),
        # Pair with stem length >= 4 (flagged in Tier 2)
        BrandCandidate(
            brand_id=20,
            brand_name="A-Clox",
            normalized_brand_name="a-clox",
            manufacturer="ACME Laboratories Ltd.",
            prefix="A",
            prefix_stem="clox",
            phonetic_key=pharma_phonetic("a-clox"),
            stem_phonetic_key=pharma_phonetic("clox"),
            canonical_generics=frozenset(["cloxacillin"]),
        ),
        BrandCandidate(
            brand_id=21,
            brand_name="A-Flox",
            normalized_brand_name="a-flox",
            manufacturer="ACME Laboratories Ltd.",
            prefix="A",
            prefix_stem="flox",
            phonetic_key=pharma_phonetic("a-flox"),
            stem_phonetic_key=pharma_phonetic("flox"),
            canonical_generics=frozenset(["flucloxacillin"]),
        ),
    ]

    pairs, stats = compute_lasa_pairs(candidates, min_stem_length=4)
    # The 3-C vs 3-F pair should be skipped because len('c') = 1 < 4
    short_stem_pair = [p for p in pairs if (p.brand_id_a == 10 and p.brand_id_b == 11)]
    assert len(short_stem_pair) == 0

    # The A-Clox vs A-Flox pair has stems 'clox' vs 'flox' (similarity 0.75)
    # They should match if threshold <= 0.75
    pairs_75, _ = compute_lasa_pairs(candidates, threshold=0.75, min_stem_length=4)
    stem_pair = [p for p in pairs_75 if (p.brand_id_a == 20 and p.brand_id_b == 21)]
    assert len(stem_pair) == 1
    assert stem_pair[0].tier == 2
    assert stem_pair[0].same_manufacturer == 1


# ============================================================================
# 5. Database Integration & Query Helper Tests
# ============================================================================

def test_db_lasa_pairs_populated():
    """Verify that lasa_pairs table in medaudit.db is populated with precomputed pairs."""
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM lasa_pairs")
    count = cursor.fetchone()[0]
    conn.close()

    assert count > 0, "lasa_pairs table must be populated after running 03_lasa_ablation.py"


def test_get_lasa_warnings_for_brand_query():
    """Query helper must return formatted warnings with disclaimers."""
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    # Find a brand that has LASA warnings
    cursor = conn.cursor()
    cursor.execute("SELECT brand_id_a FROM lasa_pairs LIMIT 1")
    row = cursor.fetchone()
    if not row:
        conn.close()
        pytest.skip("lasa_pairs table not yet populated")

    bid = row[0]
    warnings = get_lasa_warnings_for_brand(bid, conn, limit=5)
    conn.close()

    assert len(warnings) > 0
    w0 = warnings[0]
    assert "confused_brand_name" in w0
    assert "tier" in w0
    assert "edit_similarity" in w0
    assert "disclaimer" in w0
    assert w0["disclaimer"] == LASA_DISCLAIMER


def test_intra_prescription_lasa_hazards():
    """Verify detection of intra-prescription LASA pairs."""
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT brand_id_a, brand_id_b FROM lasa_pairs LIMIT 1")
    row = cursor.fetchone()
    if not row:
        conn.close()
        pytest.skip("lasa_pairs table not yet populated")

    bid_a, bid_b = row[0], row[1]
    hazards = check_intra_prescription_lasa_hazards([bid_a, bid_b], conn)
    conn.close()

    assert len(hazards) == 1
    assert hazards[0]["status"] == "FLAG"
    assert hazards[0]["brand_id_a"] == min(bid_a, bid_b)
    assert hazards[0]["brand_id_b"] == max(bid_a, bid_b)


def test_audit_prescription_lasa_integration():
    """Verify audit_prescription includes lasa_warnings and intra_prescription_lasa_hazards."""
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    # Audit 2 simple products
    result = audit_prescription([1, 2], conn=conn)
    conn.close()

    assert "intra_prescription_lasa_hazards" in result
    assert "items" in result
    for it in result["items"]:
        assert "lasa_warnings" in it
