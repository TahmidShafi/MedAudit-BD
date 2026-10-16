"""FastAPI application for MedAudit BD prescription auditor and LASA warning system."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from medaudit.api.schemas import (
    BrandLASAResponse,
    BrandLASAWarningItem,
    BrandSearchItem,
    HealthResponse,
    PrescriptionAuditRequest,
    PrescriptionAuditResponse,
)
from medaudit.audit.engine import audit_prescription
from medaudit.audit.search import search_products
from medaudit.config import PROJECT_ROOT
from medaudit.lasa.tiers import LASA_DISCLAIMER

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "processed" / "medaudit.db"
WEB_DIR = PROJECT_ROOT / "web"
STATUTORY_DISCLAIMER = (
    "Decision-support prototype only. Not a medical device and not clinical advice. "
    "Lexical LASA warnings and same-generic price rankings are not clinically validated."
)

app = FastAPI(
    title="MedAudit-BD API",
    version="1.0.0",
    description="Prescription Audit Decision-Support Prototype for Bangladesh",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create a SQLite connection configured with Row factory."""
    if not db_path.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database file not found at {db_path}. Please build the database first.",
        )
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@app.get("/v1/health", response_model=HealthResponse, tags=["System"])
def health_check() -> HealthResponse:
    """Check database connection and verify primary table row counts."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        tables = ["brands", "products", "price_packs", "lasa_pairs", "parse_anomalies"]
        counts: Dict[str, int] = {}
        for t in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {t}")
            counts[t] = cursor.fetchone()[0]

        return HealthResponse(
            status="ok",
            database_connected=True,
            table_counts=counts,
        )
    finally:
        conn.close()


@app.get("/v1/brands/search", response_model=List[BrandSearchItem], tags=["Search"])
def search_brands(
    q: str = Query(..., min_length=1, description="Brand name or prefix query string"),
    limit: int = Query(default=10, ge=1, le=50, description="Maximum candidate SKUs to return"),
) -> List[BrandSearchItem]:
    """Search catalog for brands and products matching query string using SQL prefix and RapidFuzz."""
    conn = get_db_connection()
    try:
        results = search_products(q, conn, limit=limit)
        items: List[BrandSearchItem] = []
        for r in results:
            items.append(
                BrandSearchItem(
                    product_id=r["product_id"],
                    brand_id=r.get("brand_id", 0),
                    brand_name=r["brand_name"],
                    dosage_form=r.get("dosage_form", ""),
                    strength=r.get("strength") or r.get("normalized_strength"),
                    manufacturer=r.get("manufacturer", ""),
                    similarity_score=float(r.get("similarity_score", r.get("match_score", 0.0))),
                )
            )
        return items
    finally:
        conn.close()


@app.post("/v1/prescription/audit", response_model=PrescriptionAuditResponse, tags=["Prescription Audit"])
def audit_prescription_endpoint(
    request: PrescriptionAuditRequest,
) -> PrescriptionAuditResponse:
    """Execute complete prescription audit over 2 to 8 prescribed pharmaceutical items."""
    conn = get_db_connection()
    try:
        raw_items = [it.to_audit_item() for it in request.items]
        raw_result = audit_prescription(
            items=raw_items,
            conn=conn,
            manufacturer_filter=request.manufacturer_filter,
        )

        overall_status_val = raw_result.get("overall_status", "OK")

        # Compute per-check statuses
        checks: Dict[str, str] = {}

        if overall_status_val == "AMBIGUOUS_OR_UNRESOLVED":
            checks["resolution"] = "AMBIGUOUS" if raw_result.get("ambiguous_items") else "UNRESOLVED"
            checks["duplicate_generics"] = "UNVERIFIED"
            checks["release_and_strength_hazards"] = "UNVERIFIED"
            checks["nti_locks"] = "UNVERIFIED"
            checks["alternatives"] = "UNVERIFIED"
            checks["lasa_warnings"] = "UNVERIFIED"

            return PrescriptionAuditResponse(
                overall_status=overall_status_val,
                disclaimer=STATUTORY_DISCLAIMER,
                checks=checks,
                item_count=len(request.items),
                explanation=raw_result.get("explanation"),
                ambiguous_items=raw_result.get("ambiguous_items"),
                unresolved_items=raw_result.get("unresolved_items"),
            )

        # 1. Resolution Check
        checks["resolution"] = "OK"

        # 2. Duplicate Active Ingredients
        dup_chk = raw_result.get("duplicate_check", {})
        checks["duplicate_generics"] = dup_chk.get("status", "OK")

        # 3. Release & Strength Hazards
        intra_hazards = raw_result.get("intra_prescription_hazards", [])
        shelf_hazards = raw_result.get("shelf_lookalike_hazards", [])
        if any(h.get("status") == "FLAG" for h in intra_hazards) or bool(shelf_hazards):
            checks["release_and_strength_hazards"] = "FLAG"
        elif any(h.get("status") == "UNVERIFIED" for h in intra_hazards):
            checks["release_and_strength_hazards"] = "UNVERIFIED"
        else:
            checks["release_and_strength_hazards"] = "OK"

        # 4. NTI Locks
        items_audited = raw_result.get("items", [])
        any_nti = any(it.get("is_nti", False) for it in items_audited)
        checks["nti_locks"] = "FLAG" if any_nti else "OK"

        # 5. Alternatives
        alt_statuses = [it.get("alternatives_status", "OK") for it in items_audited]
        if any(s == "FLAG" for s in alt_statuses) or any(it.get("cheaper_alternatives_count", 0) > 0 for it in items_audited):
            checks["alternatives"] = "FLAG"
        elif any(s == "UNVERIFIED" for s in alt_statuses):
            checks["alternatives"] = "UNVERIFIED"
        else:
            checks["alternatives"] = "OK"

        # 6. LASA Warnings
        intra_lasa = raw_result.get("intra_prescription_lasa_hazards", [])
        any_item_lasa = any(bool(it.get("lasa_warnings")) for it in items_audited)
        if bool(intra_lasa) or any_item_lasa:
            checks["lasa_warnings"] = "FLAG"
        else:
            checks["lasa_warnings"] = "OK"

        return PrescriptionAuditResponse(
            overall_status=overall_status_val,
            disclaimer=STATUTORY_DISCLAIMER,
            checks=checks,
            item_count=raw_result.get("item_count", len(request.items)),
            duplicate_check=dup_chk,
            intra_prescription_hazards=intra_hazards,
            shelf_lookalike_hazards=shelf_hazards,
            intra_prescription_lasa_hazards=intra_lasa,
            items=items_audited,
        )
    finally:
        conn.close()


@app.get("/v1/brands/{brand_id}/lasa", response_model=BrandLASAResponse, tags=["LASA"])
def get_brand_lasa(brand_id: int) -> BrandLASAResponse:
    """Retrieve precomputed Tier 1 and Tier 2 LASA pairs for a brand ordered by same_generic ASC, edit_similarity DESC."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Fetch target brand
        cursor.execute("SELECT brand_id, brand_name, manufacturer FROM brands WHERE brand_id = ?", (brand_id,))
        brand_row = cursor.fetchone()
        if not brand_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Brand ID {brand_id} not found in catalog.",
            )

        # Fetch precomputed LASA pairs ordered by same_generic ASC, edit_similarity DESC
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
            ORDER BY lp.same_generic ASC, lp.edit_similarity DESC
            """,
            (brand_id, brand_id, brand_id),
        )
        rows = cursor.fetchall()

        warnings: List[BrandLASAWarningItem] = []
        for r in rows:
            same_gen = bool(r[5])
            priority_label = (
                "same-generic pair (lower priority)"
                if same_gen
                else "different-generic lexical warning"
            )
            warnings.append(
                BrandLASAWarningItem(
                    confused_brand_name=r[8],
                    confused_manufacturer=r[9],
                    tier=r[2],
                    tier_name="Tier 1 (Cross-Manufacturer)" if r[2] == 1 else "Tier 2 (Same-Manufacturer)",
                    edit_similarity=float(r[3]),
                    phonetic_match=bool(r[4]),
                    same_generic=same_gen,
                    generic_priority_label=priority_label,
                    diff_preview=r[7] or "",
                    disclaimer=LASA_DISCLAIMER,
                )
            )

        return BrandLASAResponse(
            brand_id=brand_row[0],
            brand_name=brand_row[1],
            manufacturer=brand_row[2],
            warnings_count=len(warnings),
            warnings=warnings,
        )
    finally:
        conn.close()


# Mount Single-Page UI at root /
@app.get("/", include_in_schema=False)
def serve_ui():
    """Serve single-page application UI."""
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "MedAudit-BD API is running. UI file index.html not yet initialized."}


# Mount static assets if web directory exists
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
