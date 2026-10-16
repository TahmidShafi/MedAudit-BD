"""Comprehensive API test suite for MedAudit BD REST service."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from medaudit.api.main import app

client = TestClient(app)


# ============================================================================
# 1. Health Endpoint Tests
# ============================================================================

def test_health_endpoint():
    """Verify health endpoint database connectivity and exact table row counts."""
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database_connected"] is True

    counts = data["table_counts"]
    assert counts["brands"] == 14013
    assert counts["products"] == 21714
    assert counts["price_packs"] == 23096
    assert counts["lasa_pairs"] == 3358
    assert counts["parse_anomalies"] == 1087


# ============================================================================
# 2. Brand Search Tests
# ============================================================================

def test_brands_search_exact_and_prefix():
    """Verify prefix / exact search returns ranked candidate SKUs."""
    response = client.get("/v1/brands/search?q=Napa&limit=5")
    assert response.status_code == 200
    items = response.json()
    assert len(items) > 0
    first = items[0]
    assert "Napa" in first["brand_name"]
    assert "product_id" in first
    assert "brand_id" in first
    assert "dosage_form" in first
    assert "strength" in first
    assert "manufacturer" in first
    assert first["similarity_score"] == 100.0


def test_brands_search_fuzzy_misspelling():
    """Verify fuzzy search handles misspellings like 'Napaa' or 'Napx'."""
    # Napaa (fuzzy match to Napa)
    res_a = client.get("/v1/brands/search?q=Napaa&limit=5")
    assert res_a.status_code == 200
    items_a = res_a.json()
    assert len(items_a) > 0
    assert any("Napa" in it["brand_name"] for it in items_a)

    # Napx (prefix match to Napxon)
    res_x = client.get("/v1/brands/search?q=Napx&limit=5")
    assert res_x.status_code == 200
    items_x = res_x.json()
    assert len(items_x) > 0


# ============================================================================
# 3. Prescription Audit Tests
# ============================================================================

def test_audit_compound_duplicate_overlap():
    """Verify single-vs-compound Paracetamol duplicate detection (Napa + Ace Plus)."""
    payload = {
        "items": [
            {"product_id": 10452},  # Napa (500mg Paracetamol)
            {"product_id": 10557},  # Ace Plus (500mg Paracetamol + 65mg Caffeine)
        ]
    }
    response = client.post("/v1/prescription/audit", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["overall_status"] == "FLAG"
    assert "Decision-support prototype only" in data["disclaimer"]
    assert data["checks"]["duplicate_generics"] == "FLAG"
    assert data["duplicate_check"]["status"] == "FLAG"
    assert len(data["duplicate_check"]["duplicates"]) >= 1

    dup = data["duplicate_check"]["duplicates"][0]
    gen_name = dup.get("canonical_generic") or dup.get("generic")
    assert gen_name == "paracetamol"


def test_audit_release_and_10x_shelf_hazard():
    """Verify IR vs XR hazard and catalog 10x shelf look-alike warning."""
    payload = {
        "items": [
            {"product_id": 10452},  # Napa (Tablet, IR)
            {"product_id": 10454},  # Napa Extend (Tablet XR, 665mg)
        ]
    }
    response = client.post("/v1/prescription/audit", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["overall_status"] == "FLAG"
    assert data["checks"]["release_and_strength_hazards"] == "FLAG"
    assert len(data["intra_prescription_hazards"]) >= 1


def test_audit_nti_lock():
    """Verify NTI drug (Warin / Warfarin) locks brand substitution."""
    payload = {
        "items": [
            {"product_id": 3216},   # Warin (5mg Warfarin sodium, NTI)
            {"product_id": 10452},  # Napa
        ]
    }
    response = client.post("/v1/prescription/audit", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["overall_status"] == "FLAG"
    assert data["checks"]["nti_locks"] == "FLAG"

    warin_item = next(it for it in data["items"] if it["product_id"] == 3216)
    assert warin_item["is_nti"] is True
    assert warin_item["substitution_locked"] is True
    assert len(warin_item["nti_details"]) > 0


def test_audit_cheaper_alternatives_with_filter():
    """Verify same-generic cheaper alternative ranking and manufacturer filtering."""
    payload = {
        "items": [
            {"product_id": 1958},   # Seclo (20mg Omeprazole)
            {"product_id": 10452},  # Napa
        ],
        "manufacturer_filter": "Square Pharmaceuticals Ltd.",
    }
    response = client.post("/v1/prescription/audit", json=payload)
    assert response.status_code == 200
    data = response.json()

    seclo_item = next(it for it in data["items"] if it["product_id"] == 1958)
    for alt in seclo_item["top_alternatives"]:
        assert alt["manufacturer"] == "Square Pharmaceuticals Ltd."
        assert "residual_band" in alt
        assert "comparison_unit" in alt


def test_audit_ambiguous_brand_handling():
    """Verify ambiguous brand query returns candidate SKUs without silent guessing."""
    payload = {
        "items": [
            {"brand": "Napa"},      # Ambiguous: multiple dosage forms/strengths
            {"product_id": 10557},  # Ace Plus
        ]
    }
    response = client.post("/v1/prescription/audit", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["overall_status"] == "AMBIGUOUS_OR_UNRESOLVED"
    assert data["checks"]["resolution"] == "AMBIGUOUS"
    assert len(data["ambiguous_items"]) == 1
    amb = data["ambiguous_items"][0]
    assert amb["brand_name"] == "Napa"
    assert len(amb["candidate_skus"]) > 1


def test_audit_unverified_status():
    """Verify UNVERIFIED status for unparseable formulation like Pregcare (31869)."""
    payload = {
        "items": [
            {"product_id": 31869},  # Pregcare (missing/unparseable generic)
            {"product_id": 10452},  # Napa
        ]
    }
    response = client.post("/v1/prescription/audit", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["overall_status"] == "UNVERIFIED"


def test_audit_validation_item_counts():
    """Verify HTTP 422 on < 2 or > 8 items."""
    # 1 item (too few)
    res_1 = client.post("/v1/prescription/audit", json={"items": [{"product_id": 10452}]})
    assert res_1.status_code == 422

    # 9 items (too many)
    res_9 = client.post(
        "/v1/prescription/audit",
        json={"items": [{"product_id": 10452} for _ in range(9)]},
    )
    assert res_9.status_code == 422


# ============================================================================
# 4. Brand LASA Endpoint Tests
# ============================================================================

def test_brand_lasa_endpoint():
    """Verify /v1/brands/{brand_id}/lasa returns pairs ordered by same_generic ASC, edit_similarity DESC."""
    # Test brand 8318 (Napoxen) which has both cross-generic and same-generic precomputed pairs
    brand_id = 8318
    response = client.get(f"/v1/brands/{brand_id}/lasa")
    assert response.status_code == 200
    data = response.json()
    assert data["brand_id"] == brand_id
    assert data["brand_name"] == "Napoxen"
    assert data["warnings_count"] >= 1
    assert len(data["warnings"]) >= 1

    w0 = data["warnings"][0]
    assert "confused_brand_name" in w0
    assert "diff_preview" in w0
    assert "disclaimer" in w0
    assert "visual aid, not validated" in w0["diff_preview"]
    assert "lexical similarity warning, not clinically validated" in w0["disclaimer"]

    # Check ordering: same_generic ASC (False first, then True)
    seen_true = False
    for w in data["warnings"]:
        if w["same_generic"]:
            seen_true = True
        else:
            assert not seen_true, "same_generic=False must appear before same_generic=True"


def test_brand_lasa_not_found():
    """Verify HTTP 404 for non-existent brand_id."""
    response = client.get("/v1/brands/9999999/lasa")
    assert response.status_code == 404


# ============================================================================
# 5. UI Root Route Test
# ============================================================================

def test_ui_root_endpoint():
    """Verify root GET / endpoint returns 200."""
    response = client.get("/")
    assert response.status_code == 200
