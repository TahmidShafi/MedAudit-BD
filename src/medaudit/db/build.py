"""Database construction pipeline populating data/processed/medaudit.db from raw ingested data."""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from medaudit.audit.nti import is_nti_generic
from medaudit.audit.release_type import detect_release_type
from medaudit.config import PROJECT_ROOT
from medaudit.db.schema import SCHEMA_DDL
from medaudit.ingest.loader import load_dataset_records
from medaudit.parsing.generic import parse_generic
from medaudit.parsing.price import parse_price
from medaudit.parsing.strength import parse_strength

DEFAULT_RAW_CSV = PROJECT_ROOT / "data" / "raw" / "medicine.csv"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "processed" / "medaudit.db"


def extract_prefix_stem(brand_name: str) -> str:
    """Extract post-prefix stem if brand begins with a common manufacturer prefix (e.g. 'G-', 'A-')."""
    m = re.match(r"^[A-Za-z0-9]+-(.+)$", brand_name.strip())
    if m:
        return m.group(1).strip().lower()
    return brand_name.strip().lower()


def build_database(
    raw_csv_path: Path = DEFAULT_RAW_CSV,
    db_path: Path = DEFAULT_DB_PATH,
    drop_existing: bool = True,
) -> Dict[str, Any]:
    """Execute complete end-to-end database construction pipeline.

    Loads 10-column raw CSV, validates schema, populates deduplicated brands (14,013 rows),
    processes all 21,714 SKU products, builds normalized component tables, and logs all parse anomalies.

    Returns:
        Summary dict containing execution time, row counts for every table, and anomaly totals.
    """
    start_time = time.perf_counter()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if drop_existing and db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Initialize schema
    cursor.executescript(SCHEMA_DDL)
    conn.commit()

    # 2. Ingest raw CSV and construct domain records
    products_raw, brand_entities = load_dataset_records(raw_csv_path)

    # 3. Insert Brands (14,013 rows)
    brand_rows: List[Tuple[int, str, str, str, str]] = []
    for b_id, b in sorted(brand_entities.items(), key=lambda x: x[0]):
        stem = extract_prefix_stem(b.brand_name)
        brand_rows.append((b.brand_id, b.brand_name, b.normalized_brand_name, b.manufacturer, stem))

    cursor.executemany(
        """
        INSERT INTO brands (brand_id, brand_name, normalized_brand_name, manufacturer, prefix_stem)
        VALUES (?, ?, ?, ?, ?)
        """,
        brand_rows,
    )

    # 4. Process Products and Child Components
    product_rows: List[Tuple[Any, ...]] = []
    generic_comp_rows: List[Tuple[Any, ...]] = []
    strength_comp_rows: List[Tuple[Any, ...]] = []
    price_pack_rows: List[Tuple[Any, ...]] = []
    anomaly_rows: List[Tuple[Any, ...]] = []

    for r in products_raw:
        p_id = r.product_id
        b_id = r.brand_id
        raw_b_name = r.raw_brand_name
        p_type = r.type
        slug = r.slug
        dosage_form = r.dosage_form
        raw_generic = r.raw_generic
        raw_strength = r.raw_strength
        manufacturer = r.manufacturer
        raw_container = r.raw_package_container
        raw_pkg_size = r.raw_package_size

        sku_anomalies = []

        # Parse Generic
        parsed_generic = parse_generic(raw_generic, product_id=p_id)
        sku_anomalies.extend(parsed_generic.anomalies)

        for comp in parsed_generic.components:
            nti_flag = 1 if is_nti_generic(comp.canonical_generic) else 0
            generic_comp_rows.append((
                p_id,
                comp.component_order,
                comp.canonical_generic,
                comp.raw_component,
                comp.salt,
                comp.annotation,
                nti_flag,
            ))

        # Parse Strength
        gen_count = len(parsed_generic.components)
        parsed_strength = parse_strength(raw_strength, generic_component_count=gen_count, product_id=p_id)
        sku_anomalies.extend(parsed_strength.anomalies)

        norm_strength_str = None
        if parsed_strength.components:
            parts = []
            for s_comp in parsed_strength.components:
                strength_comp_rows.append((
                    p_id,
                    s_comp.component_order,
                    s_comp.amount,
                    s_comp.amount_unit,
                    s_comp.denominator_amount,
                    s_comp.denominator_unit,
                    s_comp.raw_strength,
                ))
                amt_str = f"{s_comp.amount:g} {s_comp.amount_unit}" if s_comp.amount is not None else ""
                if s_comp.denominator_amount is not None and s_comp.denominator_unit:
                    amt_str += f"/{s_comp.denominator_amount:g} {s_comp.denominator_unit}"
                parts.append(amt_str)
            norm_strength_str = " + ".join(parts) if parts else None

        # Parse Price
        parsed_price = parse_price(raw_container, raw_pkg_size, product_id=p_id)
        sku_anomalies.extend(parsed_price.anomalies)

        for pack in parsed_price.packs:
            price_pack_rows.append((
                p_id,
                pack.container_type,
                pack.volume_or_weight_value,
                pack.volume_or_weight_unit,
                pack.pack_qty,
                pack.unit_price_bdt,
                pack.pack_price_bdt,
                pack.normalized_unit_price_bdt,
                pack.comparison_unit,
                pack.residual_band,
                pack.residual_delta,
                pack.source_span,
            ))

        # Release modifier
        release_type = detect_release_type(raw_b_name, dosage_form)
        parse_status = "HAS_ANOMALY" if sku_anomalies else "VALID"

        product_rows.append((
            p_id,
            b_id,
            raw_b_name,
            p_type,
            slug,
            dosage_form,
            raw_generic,
            raw_strength,
            norm_strength_str,
            release_type,
            manufacturer,
            raw_container,
            raw_pkg_size,
            parse_status,
        ))

        # Collect anomalies
        for a in sku_anomalies:
            anomaly_rows.append((
                a.product_id,
                a.module,
                a.reason_code,
                a.raw_string,
                a.details,
            ))

    # 5. Batch Insert Products
    cursor.executemany(
        """
        INSERT INTO products (
            product_id, brand_id, raw_brand_name, type, slug, dosage_form,
            raw_generic, raw_strength, normalized_strength, release_type,
            manufacturer, raw_package_container, raw_package_size, parse_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        product_rows,
    )

    # 6. Batch Insert Generic Components
    cursor.executemany(
        """
        INSERT INTO generic_components (
            product_id, component_order, canonical_generic, raw_component,
            salt, annotation, is_nti
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        generic_comp_rows,
    )

    # 7. Batch Insert Strength Components
    cursor.executemany(
        """
        INSERT INTO strength_components (
            product_id, component_order, numeric_value, canonical_unit,
            per_volume_value, per_volume_unit, raw_component_strength
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        strength_comp_rows,
    )

    # 8. Batch Insert Price Packs
    cursor.executemany(
        """
        INSERT INTO price_packs (
            product_id, container_type, volume_or_weight_value, volume_or_weight_unit,
            pack_qty, unit_price_bdt, pack_price_bdt, normalized_unit_price_bdt,
            comparison_unit, residual_band, residual_delta, source_span
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        price_pack_rows,
    )

    # 9. Batch Insert Anomalies
    cursor.executemany(
        """
        INSERT INTO parse_anomalies (
            product_id, module, reason_code, raw_string, details
        ) VALUES (?, ?, ?, ?, ?)
        """,
        anomaly_rows,
    )

    conn.commit()

    # Query final counts
    counts: Dict[str, int] = {}
    for table in [
        "brands",
        "products",
        "generic_components",
        "strength_components",
        "price_packs",
        "parse_anomalies",
        "lasa_pairs",
    ]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = cursor.fetchone()[0]

    conn.close()
    elapsed = time.perf_counter() - start_time

    return {
        "db_path": str(db_path),
        "elapsed_seconds": round(elapsed, 3),
        "counts": counts,
    }
