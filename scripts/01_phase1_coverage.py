"""Phase 1 Empirical Coverage and Validation Script for MedAudit BD.

Executes ingest, generic parser, and strength parser across all 21,714 SKU rows.
Computes and reports:
1. Generic parser coverage (overall, allopathic, herbal)
2. Strength parser coverage (overall, allopathic, herbal)
3. Top anomaly reason codes
4. Investigation of the 66 duplicate (brand, strength, dosage form, mfg) rows.
"""

from __future__ import annotations

import sys
from collections import Counter
from typing import Dict, List

from medaudit.config import RAW_DATA_DIR, SEED
from medaudit.ingest import analyze_duplicate_combinations, load_dataset_records
from medaudit.parsing.generic import parse_generic
from medaudit.parsing.strength import parse_strength

# Ensure UTF-8 output on Windows
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_phase1_coverage():
    csv_path = RAW_DATA_DIR / "medicine.csv"
    print("=" * 70)
    print("MedAudit BD — Phase 1 Parser & Ingest Empirical Coverage Analysis")
    print("=" * 70)
    print(f"Loading raw dataset from {csv_path}...")

    products, brands = load_dataset_records(csv_path)
    total_skus = len(products)
    print(f"Loaded {total_skus:,} SKUs into domain models.")
    print(f"Deduplicated brand entities: {len(brands):,}")

    # Trackers for coverage
    # Generic coverage
    gen_stats = {
        "overall": {"full": 0, "partial": 0, "failed": 0},
        "allopathic": {"full": 0, "partial": 0, "failed": 0},
        "herbal": {"full": 0, "partial": 0, "failed": 0},
    }
    gen_anomalies = Counter()

    # Strength coverage
    str_stats = {
        "overall": {"full": 0, "partial": 0, "failed": 0},
        "allopathic": {"full": 0, "partial": 0, "failed": 0},
        "herbal": {"full": 0, "partial": 0, "failed": 0},
    }
    str_anomalies = Counter()

    # Track unparseable strength tokens for diagnosis
    unparseable_strengths = []

    for p in products:
        m_type = p.type.lower()
        if m_type not in ["allopathic", "herbal"]:
            m_type = "allopathic"

        # 1. Parse Generic
        p_gen = parse_generic(p.raw_generic, product_id=p.product_id)
        for a in p_gen.anomalies:
            gen_anomalies[a.reason_code] += 1

        if p_gen.is_valid and len(p_gen.anomalies) == 0:
            gen_stats["overall"]["full"] += 1
            gen_stats[m_type]["full"] += 1
        elif p_gen.is_valid and len(p_gen.anomalies) > 0:
            gen_stats["overall"]["partial"] += 1
            gen_stats[m_type]["partial"] += 1
        else:
            gen_stats["overall"]["failed"] += 1
            gen_stats[m_type]["failed"] += 1

        # 2. Parse Strength
        gen_comp_count = len(p_gen.components) if p_gen.is_valid else None
        p_str = parse_strength(p.raw_strength, generic_component_count=gen_comp_count, product_id=p.product_id)
        for a in p_str.anomalies:
            str_anomalies[a.reason_code] += 1
            if a.reason_code == "UNPARSEABLE_STRENGTH_TOKEN":
                unparseable_strengths.append(a.raw_string)

        if p_str.is_valid and len(p_str.anomalies) == 0:
            str_stats["overall"]["full"] += 1
            str_stats[m_type]["full"] += 1
        elif p_str.is_valid and len(p_str.anomalies) > 0:
            # e.g. valid components parsed, but component count mismatch with generic
            str_stats["overall"]["partial"] += 1
            str_stats[m_type]["partial"] += 1
        else:
            str_stats["overall"]["failed"] += 1
            str_stats[m_type]["failed"] += 1

    # Report Results
    allopathic_count = gen_stats["allopathic"]["full"] + gen_stats["allopathic"]["partial"] + gen_stats["allopathic"]["failed"]
    herbal_count = gen_stats["herbal"]["full"] + gen_stats["herbal"]["partial"] + gen_stats["herbal"]["failed"]

    print("\n" + "-" * 70)
    print("1. GENERIC PARSER COVERAGE")
    print("-" * 70)
    print(f"Overall (N = {total_skus:,}):")
    print(f"  - Fully Parsed   : {gen_stats['overall']['full']:,} ({gen_stats['overall']['full']/total_skus*100:.2f}%)")
    print(f"  - Partially Parsed: {gen_stats['overall']['partial']:,} ({gen_stats['overall']['partial']/total_skus*100:.2f}%)")
    print(f"  - Failed / Missing : {gen_stats['overall']['failed']:,} ({gen_stats['overall']['failed']/total_skus*100:.2f}%)")

    print(f"\nAllopathic SKUs (N = {allopathic_count:,}):")
    print(f"  - Fully Parsed   : {gen_stats['allopathic']['full']:,} ({gen_stats['allopathic']['full']/allopathic_count*100:.2f}%)")
    print(f"  - Partially Parsed: {gen_stats['allopathic']['partial']:,} ({gen_stats['allopathic']['partial']/allopathic_count*100:.2f}%)")
    print(f"  - Failed / Missing : {gen_stats['allopathic']['failed']:,} ({gen_stats['allopathic']['failed']/allopathic_count*100:.2f}%)")

    print(f"\nHerbal SKUs (N = {herbal_count:,}):")
    print(f"  - Fully Parsed   : {gen_stats['herbal']['full']:,} ({gen_stats['herbal']['full']/herbal_count*100:.2f}%)")
    print(f"  - Partially Parsed: {gen_stats['herbal']['partial']:,} ({gen_stats['herbal']['partial']/herbal_count*100:.2f}%)")
    print(f"  - Failed / Missing : {gen_stats['herbal']['failed']:,} ({gen_stats['herbal']['failed']/herbal_count*100:.2f}%)")

    print("\nGeneric Parse Anomalies by Reason Code:")
    for code, count in gen_anomalies.most_common():
        print(f"  - {code}: {count}")

    print("\n" + "-" * 70)
    print("2. STRENGTH PARSER COVERAGE")
    print("-" * 70)
    print(f"Overall (N = {total_skus:,}):")
    print(f"  - Fully Parsed   : {str_stats['overall']['full']:,} ({str_stats['overall']['full']/total_skus*100:.2f}%)")
    print(f"  - Partially Parsed (Component count mismatch): {str_stats['overall']['partial']:,} ({str_stats['overall']['partial']/total_skus*100:.2f}%)")
    print(f"  - Failed / Missing : {str_stats['overall']['failed']:,} ({str_stats['overall']['failed']/total_skus*100:.2f}%)")

    print(f"\nAllopathic SKUs (N = {allopathic_count:,}):")
    print(f"  - Fully Parsed   : {str_stats['allopathic']['full']:,} ({str_stats['allopathic']['full']/allopathic_count*100:.2f}%)")
    print(f"  - Partially Parsed: {str_stats['allopathic']['partial']:,} ({str_stats['allopathic']['partial']/allopathic_count*100:.2f}%)")
    print(f"  - Failed / Missing : {str_stats['allopathic']['failed']:,} ({str_stats['allopathic']['failed']/allopathic_count*100:.2f}%)")

    print(f"\nHerbal SKUs (N = {herbal_count:,}):")
    print(f"  - Fully Parsed   : {str_stats['herbal']['full']:,} ({str_stats['herbal']['full']/herbal_count*100:.2f}%)")
    print(f"  - Partially Parsed: {str_stats['herbal']['partial']:,} ({str_stats['herbal']['partial']/herbal_count*100:.2f}%)")
    print(f"  - Failed / Missing : {str_stats['herbal']['failed']:,} ({str_stats['herbal']['failed']/herbal_count*100:.2f}%)")

    print("\nStrength Parse Anomalies by Reason Code:")
    for code, count in str_anomalies.most_common():
        print(f"  - {code}: {count}")

    print("\n" + "-" * 70)
    print("3. DUPLICATE COMBINATIONS ANALYSIS (66 Duplicate Rows)")
    print("-" * 70)
    dup_report = analyze_duplicate_combinations(products)
    print(f"Total Rows: {dup_report['total_rows']:,}")
    print(f"Unique (brand, strength, dosage form, mfg) combinations: {dup_report['unique_combinations']:,}")
    print(f"Net duplicate rows: {dup_report['duplicate_rows_count']:,} across {dup_report['duplicate_group_count']} distinct SKU groups.")

    print("\nCategorization of the 65 Duplicate SKU Groups:")
    cat_counts = Counter()
    for g in dup_report["duplicate_groups"]:
        skus = g["skus"]
        # check packages
        containers = [s["package_container"] for s in skus]
        if any(c is None for c in containers) and any(c is not None for c in containers):
            cat_counts["missing_vs_populated_package"] += 1
        elif len(set(containers)) > 1:
            cat_counts["package_presentation_or_volume_variant"] += 1
        else:
            cat_counts["exact_duplicate_sku_records"] += 1

    for cat, cnt in cat_counts.most_common():
        print(f"  - {cat}: {cnt} groups")

    print("\nSample Duplicate Groups:")
    for i, g in enumerate(dup_report["duplicate_groups"][:5], 1):
        k = g["key"]
        print(f"\n[{i:02d}] {k['brand_name']} | {k['strength']} | {k['dosage_form']} | {k['manufacturer']}")
        for s in g["skus"]:
            print(f"     product_id={s['product_id']}, container={repr(s['package_container'])}, size={repr(s['package_size'])}")

    print("\n" + "=" * 70)
    print("PHASE 1 EXECUTION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    run_phase1_coverage()
