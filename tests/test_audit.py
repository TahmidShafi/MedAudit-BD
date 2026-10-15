"""Comprehensive test suite for MedAudit BD Prescription Auditor.

Contains 32 verified hand-written test prescriptions using real SKUs from data/processed/medaudit.db,
covering duplicates, release kinetics, 10x strength hazards, NTI substitution locks,
cheaper alternatives ranking, ambiguous resolutions, and unverified edge cases.
"""

import sqlite3
import pytest

from medaudit.audit.alternatives import find_same_generic_alternatives
from medaudit.audit.duplicates import check_duplicate_active_ingredients
from medaudit.audit.engine import audit_prescription
from medaudit.audit.nti import CONSERVATIVE_NTI_GENERICS, get_nti_badge, is_nti_generic
from medaudit.audit.release_type import (
    check_catalog_shelf_10x_hazards,
    check_intra_prescription_release_and_strength_hazards,
    detect_release_type,
)
from medaudit.audit.search import resolve_prescribed_item, search_products
from medaudit.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "data" / "processed" / "medaudit.db"


@pytest.fixture(scope="module")
def db_conn():
    """Connection fixture to the processed database."""
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()


# ==============================================================================
# 1. DUPLICATE ACTIVE INGREDIENTS (Prescriptions 1 to 6)
# ==============================================================================

def test_rx01_true_positive_single_generic_duplicate(db_conn):
    """Rx 1: Two different brand-name paracetamol tablets co-prescribed."""
    # 10452: Napa 500 mg Tablet, 10433: Ace 500 mg Tablet (both paracetamol 500 mg)
    res = audit_prescription([10452, 10433], conn=db_conn)
    assert res["overall_status"] == "FLAG"
    assert res["duplicate_check"]["status"] == "FLAG"
    assert res["duplicate_check"]["duplicate_count"] == 1
    dup = res["duplicate_check"]["duplicates"][0]
    assert dup["canonical_generic"] == "paracetamol"
    assert dup["occurrence_count"] == 2


def test_rx02_true_positive_single_vs_compound_duplicate(db_conn):
    """Rx 2: Single paracetamol tablet + compound Paracetamol/Caffeine tablet."""
    # 10452: Napa 500 mg, 10592: Napa Extra (Paracetamol + Caffeine)
    res = audit_prescription([10452, 10592], conn=db_conn)
    assert res["overall_status"] == "FLAG"
    assert res["duplicate_check"]["status"] == "FLAG"
    dup = res["duplicate_check"]["duplicates"][0]
    assert dup["canonical_generic"] == "paracetamol"


def test_rx03_true_positive_compound_vs_compound_duplicate(db_conn):
    """Rx 3: Paracetamol + Caffeine co-prescribed with Paracetamol + Tramadol."""
    # 10592: Napa Extra (Paracetamol + Caffeine), 10768: NapaDol (Paracetamol + Tramadol)
    res = audit_prescription([10592, 10768], conn=db_conn)
    assert res["overall_status"] == "FLAG"
    assert res["duplicate_check"]["status"] == "FLAG"
    dup = res["duplicate_check"]["duplicates"][0]
    assert dup["canonical_generic"] == "paracetamol"


def test_rx04_true_negative_clean_two_drug_prescription(db_conn):
    """Rx 4: Paracetamol + Omeprazole (no overlap, clean)."""
    # 10452: Napa 500 mg (Paracetamol), 1958: Seclo 20 mg (Omeprazole)
    res = audit_prescription([10452, 1958], conn=db_conn)
    assert res["duplicate_check"]["status"] == "OK"
    assert res["duplicate_check"]["duplicate_count"] == 0


def test_rx05_true_negative_clean_three_drug_prescription(db_conn):
    """Rx 5: Antibiotic + NSAID + PPI (Ciprofloxacin + Naproxen + Omeprazole)."""
    # 9192: Ciprocin 500 mg, 11535: Napasin 250 mg, 1958: Seclo 20 mg
    res = audit_prescription([9192, 11535, 1958], conn=db_conn)
    assert res["duplicate_check"]["status"] == "OK"
    assert res["duplicate_check"]["duplicate_count"] == 0


def test_rx06_true_negative_clean_four_drug_polypharmacy(db_conn):
    """Rx 6: Non-overlapping 4-drug chronic disease regimen."""
    # 9192 (Ciprofloxacin), 11535 (Naproxen), 1958 (Omeprazole), 10452 (Paracetamol)
    res = audit_prescription([9192, 11535, 1958, 10452], conn=db_conn)
    assert res["duplicate_check"]["status"] == "OK"


# ==============================================================================
# 2. RELEASE KINETICS & 10X DOSE HAZARDS (Prescriptions 7 to 11)
# ==============================================================================

def test_rx07_intra_prescription_release_type_mismatch(db_conn):
    """Rx 7: Napa 500 mg (IR) co-prescribed with Napa Extend 665 mg (XR)."""
    # 10452 (IR) + 10454 (XR)
    res = audit_prescription([10452, 10454], conn=db_conn)
    assert res["overall_status"] == "FLAG"
    hazards = res["intra_prescription_hazards"]
    rel_mismatches = [h for h in hazards if h["hazard_type"] == "RELEASE_TYPE_MISMATCH"]
    assert len(rel_mismatches) == 1
    assert rel_mismatches[0]["item_a"]["release_type"] != rel_mismatches[0]["item_b"]["release_type"]


def test_rx08_intra_prescription_10x_strength_hazard(db_conn):
    """Rx 8: Co-prescribing items of the same generic differing by >= 10x dose."""
    # Farin 1 mg (28168) and Farin 10x or custom items
    items = [
        {"product_id": 28168, "canonical_generics": ["warfarin"], "numeric_strength": 1.0, "strength_unit": "mg", "release_type": "IR"},
        {"product_id": 99991, "canonical_generics": ["warfarin"], "numeric_strength": 10.0, "strength_unit": "mg", "release_type": "IR"},
    ]
    hazards = check_intra_prescription_release_and_strength_hazards(items)
    strength_hazards = [h for h in hazards if h["hazard_type"] == "10X_STRENGTH_INTRA_PRESCRIPTION"]
    assert len(strength_hazards) == 1
    assert strength_hazards[0]["ratio"] == 10.0


def test_rx09_catalog_shelf_10x_lookalike_cortan(db_conn):
    """Rx 9: Cortan 2 mg has sibling Cortan 20 mg on the catalog shelf (10x hazard)."""
    # Cortan 2 mg: 22289, Cortan 20 mg: 5796
    shelf_res = check_catalog_shelf_10x_hazards(22289, db_conn)
    assert shelf_res["status"] == "FLAG"
    assert len(shelf_res["hazards"]) >= 1
    assert any(h["sibling_product_id"] == 5796 for h in shelf_res["hazards"])


def test_rx10_catalog_shelf_10x_lookalike_cytabin(db_conn):
    """Rx 10: Cytabin 100 mg has sibling Cytabin 1000 mg in catalog."""
    # Cytabin 100 mg: 15045, Cytabin 1000 mg: 31245
    shelf_res = check_catalog_shelf_10x_hazards(15045, db_conn)
    assert shelf_res["status"] == "FLAG"
    assert any(h["sibling_product_id"] == 31245 for h in shelf_res["hazards"])


def test_rx11_catalog_shelf_10x_lookalike_dcap(db_conn):
    """Rx 11: D-Cap 2000 IU has sibling D-Cap 20000 IU in catalog."""
    # 31050 (2000 IU) and 19316 (20000 IU)
    shelf_res = check_catalog_shelf_10x_hazards(31050, db_conn)
    assert shelf_res["status"] == "FLAG"
    assert any(h["sibling_product_id"] == 19316 for h in shelf_res["hazards"])


# ==============================================================================
# 3. NTI SUBSTITUTION LOCKS (Prescriptions 12 to 20)
# ==============================================================================

def test_rx12_nti_substitution_lock_warfarin(db_conn):
    """Rx 12: Warfarin brand substitution must be strictly locked."""
    # 28168: Farin 1 mg (Warfarin Sodium)
    alt = find_same_generic_alternatives(28168, db_conn)
    assert alt["status"] == "LOCKED"
    assert alt["substitution_locked"] is True
    assert len(alt["alternatives"]) == 0
    assert "Narrow Therapeutic Index" in alt["explanation"]


def test_rx13_nti_substitution_lock_levothyroxine(db_conn):
    """Rx 13: Levothyroxine brand substitution locked."""
    # 5733: Thyrolar 50 mcg (Levothyroxine Sodium)
    alt = find_same_generic_alternatives(5733, db_conn)
    assert alt["status"] == "LOCKED"
    assert alt["substitution_locked"] is True


def test_rx14_nti_substitution_lock_digoxin(db_conn):
    """Rx 14: Digoxin brand substitution locked."""
    # 2457: Digoxen 0.2 mg
    alt = find_same_generic_alternatives(2457, db_conn)
    assert alt["status"] == "LOCKED"
    assert alt["substitution_locked"] is True


def test_rx15_nti_substitution_lock_lithium(db_conn):
    """Rx 15: Lithium brand substitution locked."""
    # 4443: Lithosun SR 400 mg
    alt = find_same_generic_alternatives(4443, db_conn)
    assert alt["status"] == "LOCKED"
    assert alt["substitution_locked"] is True


def test_rx16_nti_substitution_lock_insulin_pen(db_conn):
    """Rx 16: Insulin Glargine prefilled pen locked."""
    # 26939: Abasaglar Pen
    alt = find_same_generic_alternatives(26939, db_conn)
    assert alt["status"] == "LOCKED"
    assert alt["substitution_locked"] is True


def test_rx17_nti_substitution_lock_insulin_cartridge(db_conn):
    """Rx 17: Insulin Glargine cartridge locked."""
    # 26940: Abasaglar Cartridge
    alt = find_same_generic_alternatives(26940, db_conn)
    assert alt["status"] == "LOCKED"
    assert alt["substitution_locked"] is True


def test_rx18_nti_substitution_lock_carbamazepine(db_conn):
    """Rx 18: Carbamazepine locked."""
    # 4797: Anleptic CR
    alt = find_same_generic_alternatives(4797, db_conn)
    assert alt["status"] == "LOCKED"
    assert alt["substitution_locked"] is True


def test_rx19_nti_substitution_lock_tacrolimus(db_conn):
    """Rx 19: Tacrolimus locked."""
    # 15166: Crilomus 1 mg
    alt = find_same_generic_alternatives(15166, db_conn)
    assert alt["status"] == "LOCKED"
    assert alt["substitution_locked"] is True


def test_rx20_nti_substitution_lock_theophylline(db_conn):
    """Rx 20: Theophylline locked."""
    # 3643: Arofil SR 300 mg
    alt = find_same_generic_alternatives(3643, db_conn)
    assert alt["status"] == "LOCKED"
    assert alt["substitution_locked"] is True


# ==============================================================================
# 4. CHEAPER SAME-GENERIC ALTERNATIVES (Prescriptions 21 to 25)
# ==============================================================================

def test_rx21_cheaper_alternatives_paracetamol_tablet(db_conn):
    """Rx 21: Napa 500 mg tablet cheaper same-generic alternative ranking."""
    # 10452: Napa 500 mg Tablet
    alt = find_same_generic_alternatives(10452, db_conn, limit=5)
    assert alt["status"] == "OK"
    assert alt["substitution_locked"] is False
    assert alt["alternatives_count"] > 0
    # Every alternative must be labeled "same-generic alternative", NEVER "bioequivalent"
    for a in alt["alternatives"]:
        assert a["relationship"] == "same-generic alternative"
        assert a["relationship"] != "bioequivalent"
        assert a["dosage_form"] == "Tablet"
        assert a["normalized_strength"] == "500 mg"


def test_rx22_cheaper_alternatives_paracetamol_syrup_per_ml(db_conn):
    """Rx 22: Napa oral suspension (120 mg/5 ml) compared strictly per_ml."""
    # 10456: Napa Oral Suspension 120 mg/5 ml
    alt = find_same_generic_alternatives(10456, db_conn)
    assert alt["status"] == "OK"
    assert alt["prescribed_product"]["comparison_unit"] == "per_ml"
    for a in alt["alternatives"]:
        assert a["comparison_unit"] == "per_ml"


def test_rx23_cheaper_alternatives_manufacturer_filter(db_conn):
    """Rx 23: Napa 500 mg tablet filtered by specific manufacturer."""
    # 10452: Napa 500 mg, filter for Square Pharmaceuticals Ltd.
    alt = find_same_generic_alternatives(10452, db_conn, manufacturer_filter="Square Pharmaceuticals Ltd.")
    assert alt["status"] == "OK"
    for a in alt["alternatives"]:
        assert a["manufacturer"] == "Square Pharmaceuticals Ltd."


def test_rx24_multi_tier_vial_pricing_edge_case_17285(db_conn):
    """Rx 24: Product 17285 (30 mg, 100 mg, 300 mg multi-tier vial) matches correctly."""
    alt = find_same_generic_alternatives(17285, db_conn)
    assert alt["status"] == "OK"
    assert alt["prescribed_product"]["comparison_unit"] == "per_unit"
    assert alt["prescribed_product"]["normalized_unit_price_bdt"] > 0


def test_rx25_multi_tier_vial_pricing_edge_case_28654(db_conn):
    """Rx 25: Product 28654 (10 mg vs 50 mg vial) matches correctly."""
    alt = find_same_generic_alternatives(28654, db_conn)
    assert alt["status"] == "OK"
    assert alt["prescribed_product"]["normalized_unit_price_bdt"] > 0


# ==============================================================================
# 5. AMBIGUOUS & FUZZY BRAND SEARCH RESOLUTION (Prescriptions 26 to 28)
# ==============================================================================

def test_rx26_ambiguous_brand_resolution_napa(db_conn):
    """Rx 26: Passing 'Napa' without strength/form must return AMBIGUOUS status."""
    res = resolve_prescribed_item("Napa", db_conn)
    assert res["resolution_status"] == "AMBIGUOUS"
    assert res["candidate_count"] > 1
    assert any(c["dosage_form"] == "Tablet" for c in res["candidates"])
    assert any(c["dosage_form"] == "Oral Suspension" for c in res["candidates"])


def test_rx27_ambiguous_brand_resolution_seclo(db_conn):
    """Rx 27: Passing 'Seclo' without strength returns AMBIGUOUS."""
    res = resolve_prescribed_item("Seclo", db_conn)
    assert res["resolution_status"] == "AMBIGUOUS"
    assert res["candidate_count"] >= 2


def test_rx28_exact_brand_form_strength_resolution(db_conn):
    """Rx 28: Providing brand name + dosage form + strength resolves cleanly."""
    res = resolve_prescribed_item(
        {"brand_name": "Napa", "dosage_form": "Tablet", "strength": "500 mg"},
        db_conn,
    )
    assert res["resolution_status"] == "RESOLVED"
    assert res["product_id"] == 10452
    assert res["brand_name"] == "Napa"


# ==============================================================================
# 6. UNVERIFIED ANOMALOUS SKUS (Prescriptions 29 to 32)
# ==============================================================================

def test_rx29_unverified_missing_generic_sku_31869(db_conn):
    """Rx 29: Prescribing SKU 31869 (Pregcare, null generic) returns UNVERIFIED."""
    res = audit_prescription([31869, 10452], conn=db_conn)
    assert res["duplicate_check"]["status"] == "UNVERIFIED"
    assert len(res["duplicate_check"]["unverified_reasons"]) > 0


def test_rx30_unverified_missing_generic_sku_32474(db_conn):
    """Rx 30: Prescribing SKU 32474 (Affrox, null generic) returns UNVERIFIED."""
    res = audit_prescription([32474, 1958], conn=db_conn)
    assert res["duplicate_check"]["status"] == "UNVERIFIED"


def test_rx31_unverified_unavailable_price_cholera_fluid_14885(db_conn):
    """Rx 31: Cholera fluid (14885, Not for sale) returns UNVERIFIED alternatives."""
    alt = find_same_generic_alternatives(14885, db_conn)
    assert alt["status"] == "UNVERIFIED"
    assert "no valid verified price" in alt["explanation"]


def test_rx32_unverified_unparseable_price_minipil_30055(db_conn):
    """Rx 32: Minipil (30055, irregular container text) returns UNVERIFIED."""
    alt = find_same_generic_alternatives(30055, db_conn)
    assert alt["status"] == "UNVERIFIED"
