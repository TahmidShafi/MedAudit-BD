"""Automatic database bootstrapping and initialization for MedAudit-BD.

Ensures data/processed/medaudit.db exists, contains all tables, and is fully
populated with products, price packs, and precomputed LASA pairs. If missing
(e.g., in a clean container deployment), downloads medicine.csv from Hugging Face
and builds the database automatically.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict

from huggingface_hub import hf_hub_download

from medaudit.config import (
    DEFAULT_DB_PATH,
    DEFAULT_RAW_CSV,
    HF_DATASET_NAME,
)
from medaudit.db.build import build_database
from medaudit.lasa.candidates import load_brand_candidates
from medaudit.lasa.tiers import (
    compute_full_similarity_matrix,
    compute_lasa_pairs,
    save_lasa_pairs_to_db,
)

logger = logging.getLogger("medaudit.bootstrap")

REQUIRED_TABLE_COUNTS: Dict[str, int] = {
    "brands": 14013,
    "products": 21714,
    "price_packs": 23096,
    "lasa_pairs": 3358,
    "parse_anomalies": 1087,
}


def is_database_complete(db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Verify that the database file exists and all required tables have data."""
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        for table, min_count in REQUIRED_TABLE_COUNTS.items():
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            row = cur.fetchone()
            if not row or row[0] < min_count:
                conn.close()
                return False
        conn.close()
        return True
    except Exception:
        return False


def ensure_raw_dataset(raw_csv_path: Path = DEFAULT_RAW_CSV) -> Path:
    """Ensure raw dataset CSV exists, downloading from Hugging Face if absent."""
    if raw_csv_path.exists() and raw_csv_path.stat().st_size > 0:
        return raw_csv_path

    raw_csv_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[bootstrap] Downloading {HF_DATASET_NAME} medicine.csv from Hugging Face...")
    downloaded_file = hf_hub_download(
        repo_id=HF_DATASET_NAME,
        filename="medicine.csv",
        repo_type="dataset",
        local_dir=str(raw_csv_path.parent),
    )
    return Path(downloaded_file)


def build_lasa_pairs(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Compute and persist 2-tier LASA pairs into SQLite database."""
    conn = sqlite3.connect(db_path)
    print("[bootstrap] Loading brand candidates for LASA precomputation...")
    candidates = load_brand_candidates(conn)
    names = [b.normalized_brand_name for b in candidates]

    print(f"[bootstrap] Computing dense similarity matrix for {len(names)} brands...")
    sim_matrix = compute_full_similarity_matrix(names)

    print("[bootstrap] Computing Mode B 2-Tier LASA pairs...")
    pairs, stats = compute_lasa_pairs(candidates, similarity_matrix=sim_matrix)

    inserted = save_lasa_pairs_to_db(pairs, conn)
    conn.close()
    print(f"[bootstrap] Persisted {inserted:,} LASA pairs into {db_path.name}.")
    return inserted


def ensure_database(
    db_path: Path = DEFAULT_DB_PATH,
    raw_csv_path: Path = DEFAULT_RAW_CSV,
    force_rebuild: bool = False,
) -> Path:
    """Ensure medaudit.db is fully built and populated. If not, builds it."""
    if not force_rebuild and is_database_complete(db_path):
        print(f"[bootstrap] Database verified complete at {db_path}.")
        return db_path

    t0 = time.perf_counter()
    print("=" * 70)
    print(f"[bootstrap] Initializing MedAudit-BD database at {db_path}...")
    print("=" * 70)

    # 1. Download CSV if missing
    csv_file = ensure_raw_dataset(raw_csv_path)

    # 2. Build core tables
    db_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[bootstrap] Ingesting {csv_file.name} and building relational schema...")
    res = build_database(raw_csv_path=csv_file, db_path=db_path)
    print(f"[bootstrap] Core database built in {res['elapsed_seconds']:.2f}s.")

    # 3. Compute and populate LASA pairs
    build_lasa_pairs(db_path)

    elapsed = time.perf_counter() - t0
    print(f"[bootstrap] Full database ready in {elapsed:.2f}s.")
    print("=" * 70)
    return db_path


def main():
    """CLI entrypoint for database bootstrapping."""
    if sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ensure_database()


if __name__ == "__main__":
    main()
