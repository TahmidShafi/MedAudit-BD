"""Script 02: Evaluation of Price Parser and 3-Band Arithmetic Residual Classifier.

Evaluates src/medaudit/parsing/price.py against:
1. All 21,714 SKU records in data/raw/medicine.csv.
2. The locked 250-row gold-standard fixture in tests/fixtures/price_labels.csv.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from medaudit.config import PROJECT_ROOT
from medaudit.parsing.price import parse_price

RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "medicine.csv"
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "price_labels.csv"

EVAL_FIELDS = [
    "container_type",
    "volume_or_weight_value",
    "volume_or_weight_unit",
    "pack_qty",
    "unit_price_bdt",
    "pack_price_bdt",
    "normalized_unit_price_bdt",
    "comparison_unit",
]


def _packs_equal(parsed_pack: Any, expected_dict: Dict[str, Any]) -> bool:
    """Compare a parsed PricePack object with an expected JSON pack dictionary."""
    for field in EVAL_FIELDS:
        v_parsed = getattr(parsed_pack, field, None)
        v_exp = expected_dict.get(field)
        if v_parsed != v_exp:
            if isinstance(v_parsed, (int, float)) and isinstance(v_exp, (int, float)):
                if abs(float(v_parsed) - float(v_exp)) < 0.0001:
                    continue
            return False
    return True


def evaluate_fixture() -> Dict[str, Any]:
    """Evaluate price parser against the locked 250-row gold-standard fixture."""
    print("=" * 80)
    print("PART 1: EVALUATION AGAINST LOCKED 250-ROW GROUND-TRUTH FIXTURE")
    print("=" * 80)

    df_fixture = pd.read_csv(FIXTURE_PATH, encoding="utf-8")
    total_fixture = len(df_fixture)
    total_matched = 0

    category_stats: Dict[str, Dict[str, int]] = {}
    mismatches: List[Dict[str, Any]] = []

    for _, row in df_fixture.iterrows():
        p_id = int(row["product_id"])
        category = row["format_category"]
        raw_c = row["raw_package_container"]
        raw_s = row["raw_package_size"]
        expected_packs = json.loads(row["expected_packs_json"])

        if category not in category_stats:
            category_stats[category] = {"total": 0, "matched": 0}
        category_stats[category]["total"] += 1

        parsed_result = parse_price(raw_c, raw_s, product_id=p_id)
        parsed_packs = parsed_result.packs

        is_match = len(parsed_packs) == len(expected_packs)
        if is_match:
            for p_parsed, p_exp in zip(parsed_packs, expected_packs):
                if not _packs_equal(p_parsed, p_exp):
                    is_match = False
                    break

        if is_match:
            total_matched += 1
            category_stats[category]["matched"] += 1
        else:
            mismatches.append({
                "product_id": p_id,
                "category": category,
                "raw_container": raw_c,
                "raw_size": raw_s,
                "parsed_packs": [p.model_dump() for p in parsed_packs],
                "expected_packs": expected_packs,
            })

    overall_accuracy = (total_matched / total_fixture) * 100.0
    print(f"\nOverall Exact-Match Accuracy: {total_matched}/{total_fixture} ({overall_accuracy:.2f}%)\n")
    print(f"{'Format Category':<28} {'Matched':<10} {'Total':<10} {'Accuracy':<10}")
    print("-" * 60)
    for cat, stats in sorted(category_stats.items()):
        cat_acc = (stats["matched"] / stats["total"]) * 100.0
        print(f"{cat:<28} {stats['matched']:<10} {stats['total']:<10} {cat_acc:.2f}%")

    if mismatches:
        print("\n" + "-" * 80)
        print(f"MISMATCHED ROWS ({len(mismatches)} total):")
        print("-" * 80)
        for m in mismatches:
            print(f"Product ID: {m['product_id']} | Category: {m['category']}")
            print(f"  Raw Container: {repr(m['raw_container'])}")
            print(f"  Parsed Output:   {m['parsed_packs']}")
            print(f"  Expected Output: {m['expected_packs']}\n")

    return {
        "total_fixture": total_fixture,
        "total_matched": total_matched,
        "overall_accuracy": overall_accuracy,
        "category_stats": category_stats,
        "mismatches": mismatches,
    }


def evaluate_full_dataset() -> Dict[str, Any]:
    """Evaluate price parser against all 21,714 SKUs in data/raw/medicine.csv."""
    print("=" * 80)
    print("PART 2: EVALUATION AGAINST FULL 21,714 SKU DATASET (data/raw/medicine.csv)")
    print("=" * 80)

    df_raw = pd.read_csv(RAW_DATA_PATH)
    total_skus = len(df_raw)

    skus_with_valid_packs = 0
    skus_unavailable = 0
    skus_failing_unparseable = 0

    all_extracted_packs: List[Any] = []
    residual_band_counts = {
        "BAND_1_EXACT": 0,
        "BAND_2_ROUNDING_DRIFT": 0,
        "BAND_3_HARD_DISCREPANCY": 0,
        "SINGLE_PRICE_NO_PACK_CHECK": 0,
    }
    band_3_examples: List[Dict[str, Any]] = []
    band_2_examples: List[Dict[str, Any]] = []
    unparseable_sku_samples: List[Dict[str, Any]] = []

    for _, row in df_raw.iterrows():
        p_id = int(row["brand id"])
        brand_name = str(row["brand name"])
        raw_c = row["package container"]
        raw_s = row["Package Size"]

        parsed_result = parse_price(raw_c, raw_s, product_id=p_id)

        # Check if price unavailable
        c_str = str(raw_c).strip().lower() if pd.notna(raw_c) else ""
        if not c_str or c_str in ["nan", "none", "price unavailable", "not for sale"]:
            skus_unavailable += 1

        if parsed_result.is_valid:
            skus_with_valid_packs += 1
        elif c_str and c_str not in ["nan", "none", "price unavailable", "not for sale"]:
            skus_failing_unparseable += 1
            if len(unparseable_sku_samples) < 15:
                unparseable_sku_samples.append({
                    "product_id": p_id,
                    "brand_name": brand_name,
                    "raw_container": raw_c,
                    "raw_size": raw_s,
                    "anomalies": [a.model_dump() for a in parsed_result.anomalies],
                })

        for pack in parsed_result.packs:
            all_extracted_packs.append(pack)
            b = pack.residual_band
            if b in residual_band_counts:
                residual_band_counts[b] += 1
            if b == "BAND_3_HARD_DISCREPANCY":
                band_3_examples.append({
                    "product_id": p_id,
                    "brand_name": brand_name,
                    "raw_container": raw_c,
                    "unit_price_bdt": pack.unit_price_bdt,
                    "pack_qty": pack.pack_qty,
                    "pack_price_bdt": pack.pack_price_bdt,
                    "residual_delta": pack.residual_delta,
                    "tolerance": round(0.01 * (pack.pack_qty or 1), 4),
                })
            elif b == "BAND_2_ROUNDING_DRIFT":
                if len(band_2_examples) < 15:
                    band_2_examples.append({
                        "product_id": p_id,
                        "brand_name": brand_name,
                        "raw_container": raw_c,
                        "unit_price_bdt": pack.unit_price_bdt,
                        "pack_qty": pack.pack_qty,
                        "pack_price_bdt": pack.pack_price_bdt,
                        "residual_delta": pack.residual_delta,
                        "tolerance": round(0.01 * (pack.pack_qty or 1), 4),
                    })

    print(f"\nTotal Dataset SKUs: {total_skus:,}")
    print(
        f"SKUs with >=1 Valid Parsed Pack: {skus_with_valid_packs:,} "
        f"({skus_with_valid_packs / total_skus * 100:.2f}%)"
    )
    print(
        f"SKUs with Price Unavailable / Null / Not for Sale: {skus_unavailable:,} "
        f"({skus_unavailable / total_skus * 100:.2f}%)"
    )
    print(
        f"SKUs Failing with Unparseable Tokens: {skus_failing_unparseable:,} "
        f"({skus_failing_unparseable / total_skus * 100:.2f}%)"
    )
    print(f"\nTotal Extracted PricePack Objects: {len(all_extracted_packs):,}\n")

    print(f"{'Residual Classification Band':<30} {'Packs':<10} {'Percentage':<10}")
    print("-" * 55)
    total_packs = len(all_extracted_packs)
    for band, count in residual_band_counts.items():
        pct = (count / total_packs * 100.0) if total_packs > 0 else 0.0
        print(f"{band:<30} {count:<10,} {pct:.2f}%")

    print("\n" + "-" * 80)
    print(f"BAND_3_HARD_DISCREPANCY EXAMPLES (Total found: {len(band_3_examples)}):")
    print("-" * 80)
    if band_3_examples:
        for ex in band_3_examples[:15]:
            print(
                f"[{ex['product_id']}] {ex['brand_name']}: unit={ex['unit_price_bdt']}, "
                f"qty={ex['pack_qty']}, pack_price={ex['pack_price_bdt']} -> "
                f"delta={ex['residual_delta']} (tolerance={ex['tolerance']})"
            )
            print(f"  raw: {ex['raw_container']}")
    else:
        print("None found! All explicit multi-pack pricing tiers satisfy arithmetic residual tolerance.")
        print("Showing representative BAND_2_ROUNDING_DRIFT examples instead:")
        for ex in band_2_examples[:10]:
            print(
                f"  [{ex['product_id']}] {ex['brand_name']}: unit=৳ {ex['unit_price_bdt']}, "
                f"qty={ex['pack_qty']}, pack_price=৳ {ex['pack_price_bdt']} -> "
                f"drift delta={ex['residual_delta']} (tolerance={ex['tolerance']})"
            )

    if unparseable_sku_samples:
        print("\n" + "-" * 80)
        print(f"SAMPLE UNPARSEABLE SKUS ({len(unparseable_sku_samples)} shown):")
        print("-" * 80)
        for s in unparseable_sku_samples:
            print(f"[{s['product_id']}] {s['brand_name']}: {s['raw_container']}")

    return {
        "total_skus": total_skus,
        "skus_with_valid_packs": skus_with_valid_packs,
        "skus_unavailable": skus_unavailable,
        "skus_failing_unparseable": skus_failing_unparseable,
        "total_extracted_packs": total_packs,
        "residual_band_counts": residual_band_counts,
        "band_3_count": len(band_3_examples),
        "band_3_examples": band_3_examples,
        "band_2_examples": band_2_examples,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    evaluate_fixture()
    print("\n")
    evaluate_full_dataset()


if __name__ == "__main__":
    main()
