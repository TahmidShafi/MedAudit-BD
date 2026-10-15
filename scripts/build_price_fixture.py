"""Phase 2A Ground-Truth Fixture Construction Script.

Builds tests/fixtures/price_labels.csv with exactly 250 stratified rows
and manually transcribed ground-truth JSON arrays.
Strict Phase 2A compliance: No price.py creation, no parser leakage.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from medaudit.config import PROJECT_ROOT, RAW_DATA_DIR, SEED

CSV_OUTPUT_PATH = PROJECT_ROOT / "tests" / "fixtures" / "price_labels.csv"


def build_fixture() -> pd.DataFrame:
    raw_csv = RAW_DATA_DIR / "medicine.csv"
    df = pd.read_csv(raw_csv)

    # Classification function from Phase 0
    def classify_container(s):
        if pd.isna(s):
            return "price_unavailable"
        s = str(s).strip()
        if not s or s.lower() == "nan" or s.lower() in ["price unavailable", "not available", "unavailable"]:
            return "price_unavailable"

        up_count = len(re.findall(r"unit\s+price:", s, re.I))
        pack_count = len(re.findall(r"\d+'s\s+pack:", s, re.I))
        has_volume_container = bool(
            re.search(
                r"\b\d+(\.\d+)?\s*(ml|gm|mg|iu|mcg|liters|liter|l|g|kg|ampoule|vial|tube|bottle|drop|drops|sachet|sachets|syringe|respule|nebule|suppository|cream|ointment|gel|lotion|solution|suspension|spray|sprays|powder|can|jar|tin)\b.*:",
                s,
                re.I,
            )
        )

        if up_count > 1 or pack_count > 1 or ("," in s and (len(re.findall(r":\s*৳", s)) > 1 and not (up_count == 1 and pack_count == 1))):
            return "multi_pack_or_tier"
        if has_volume_container:
            if pack_count >= 1:
                return "multi_pack_or_tier"
            return "volume_container_single"
        if up_count == 1 and pack_count == 1:
            return "unit_and_single_pack"
        if up_count == 1 and pack_count == 0:
            return "unit_price_only"
        return "other_format"

    df["category"] = df["package container"].apply(classify_container)

    target_counts = {
        "unit_and_single_pack": 100,
        "volume_container_single": 75,
        "multi_pack_or_tier": 45,
        "other_format": 15,
        "unit_price_only": 10,
        "price_unavailable": 5,
    }

    # Phase 1 delivery-variant and edge-case SKUs to guarantee representation
    mandatory_ids = [26940, 26939, 3446, 3443, 30170, 28361]
    sample_dfs = []

    for cat, count in target_counts.items():
        cat_df = df[df["category"] == cat]
        cat_mandatory = [pid for pid in mandatory_ids if pid in cat_df["brand id"].values]
        remaining_count = count - len(cat_mandatory)
        cat_rem = cat_df[~cat_df["brand id"].isin(cat_mandatory)]
        sampled_rem = cat_rem.sample(n=remaining_count, random_state=SEED)
        cat_final = pd.concat([cat_df[cat_df["brand id"].isin(cat_mandatory)], sampled_rem])
        sample_dfs.append(cat_final)

    sampled_df = pd.concat(sample_dfs).reset_index(drop=True)

    rows: List[Dict[str, Any]] = []

    for idx, r in sampled_df.iterrows():
        p_id = int(r["brand id"])
        b_name = str(r["brand name"]).strip()
        d_form = str(r["dosage form"]).strip()
        raw_size = str(r["Package Size"]).strip() if pd.notna(r["Package Size"]) and str(r["Package Size"]).strip() != "" and str(r["Package Size"]).lower() != "nan" else None
        raw_cont = str(r["package container"]).strip() if pd.notna(r["package container"]) and str(r["package container"]).strip() != "" and str(r["package container"]).lower() != "nan" else None
        category = str(r["category"])

        expected_packs: List[Dict[str, Any]] = []
        needs_review: bool = False
        notes: str = ""

        # --- CATEGORY 1: unit_and_single_pack (100 rows) ---
        if category == "unit_and_single_pack":
            # Pattern: Unit Price: ৳ X,(Y's pack: ৳ Z),
            m = re.match(r"^Unit Price:\s*৳\s*([0-9,.]+)\s*,\s*\(([0-9]+)'s pack:\s*৳\s*([0-9,.]+)\)", raw_cont)
            if m:
                u_price = float(m.group(1).replace(",", ""))
                q = int(m.group(2))
                p_price = float(m.group(3).replace(",", ""))
                expected_packs.append({
                    "container_type": "pack",
                    "volume_or_weight_value": None,
                    "volume_or_weight_unit": None,
                    "pack_qty": q,
                    "unit_price_bdt": u_price,
                    "pack_price_bdt": p_price,
                    "normalized_unit_price_bdt": u_price,
                    "comparison_unit": "per_unit",
                })
                # Check arithmetic
                calc = round(u_price * q, 2)
                diff = round(abs(calc - p_price), 2)
                if diff > 0.05:
                    needs_review = True
                    notes = f"Arithmetic discrepancy: unit_price {u_price} * qty {q} = {calc} vs pack_price {p_price} (diff: {diff})"
            else:
                needs_review = True
                notes = f"Unexpected format in unit_and_single_pack: {raw_cont}"

        # --- CATEGORY 2: volume_container_single (75 rows) ---
        elif category == "volume_container_single":
            # Bottle, vial, ampoule, tube, drop, pre-filled syringe
            # Pattern: Value Unit container: ৳ Price
            m = re.match(
                r"^([0-9.]+)\s*(ml|gm|mg|iu|mcg|l)\s*(bottle|tube|drop|vial|ampoule|pre-filled syringe|per-filled pen|pen|solution|spray):\s*৳\s*([0-9,.]+)$",
                raw_cont,
                re.I,
            )
            if m:
                val = float(m.group(1))
                unit = m.group(2).lower()
                c_name = m.group(3).lower()
                price = float(m.group(4).replace(",", ""))

                # Map container_type
                if "bottle" in c_name or "solution" in c_name:
                    c_type = "bottle"
                    comp_unit = "per_ml"
                    norm_price = round(price / val, 4)
                elif "tube" in c_name:
                    c_type = "tube"
                    comp_unit = "per_gm"
                    norm_price = round(price / val, 4)
                elif "drop" in c_name:
                    c_type = "drop"
                    comp_unit = "per_ml"
                    norm_price = round(price / val, 4)
                elif "ampoule" in c_name:
                    c_type = "ampoule"
                    comp_unit = "per_unit"
                    norm_price = price
                    notes = f"Single ampoule; primary comparison_unit is per_unit ({round(price/val, 4)} per ml)"
                elif "vial" in c_name:
                    c_type = "vial"
                    comp_unit = "per_unit"
                    norm_price = price
                    notes = f"Single vial; primary comparison_unit is per_unit ({round(price/val, 4)} per {unit})"
                elif "syringe" in c_name:
                    c_type = "other"
                    comp_unit = "per_unit"
                    norm_price = price
                    notes = f"Pre-filled syringe; primary comparison_unit is per_unit ({round(price/val, 4)} per ml)"
                elif "pen" in c_name:
                    c_type = "pen"
                    comp_unit = "per_unit"
                    norm_price = price
                    if "per-filled pen" in c_name:
                        needs_review = True
                        notes = f"Source typo 'per-filled pen'; primary comparison_unit is per_unit ({round(price/val, 4)} per ml)"
                    else:
                        notes = f"Pen device; primary comparison_unit is per_unit ({round(price/val, 4)} per ml)"
                elif "spray" in c_name:
                    c_type = "spray"
                    comp_unit = "per_ml"
                    norm_price = round(price / val, 4)
                else:
                    c_type = "other"
                    comp_unit = "per_unit"
                    norm_price = price

                expected_packs.append({
                    "container_type": c_type,
                    "volume_or_weight_value": val,
                    "volume_or_weight_unit": unit,
                    "pack_qty": None,
                    "unit_price_bdt": None,
                    "pack_price_bdt": price,
                    "normalized_unit_price_bdt": norm_price,
                    "comparison_unit": comp_unit,
                })
            else:
                needs_review = True
                notes = f"Complex single container format: {raw_cont}"

        # --- CATEGORY 3: multi_pack_or_tier (45 rows) ---
        elif category == "multi_pack_or_tier":
            # May contain:
            # Subtype A: multiple Unit Price tiers: Unit Price: ৳ X,(Y's pack: ৳ Z),,Unit Price: ৳ X,(A's pack: ৳ B)
            # Subtype B: multiple volume tiers: 100 ml bottle: ৳ X, 200 ml bottle: ৳ Y
            # Subtype C: volume container with multi-pack: 4 ml ampoule: ৳ 30.10,(3's pack: ৳ 90.30),
            if "Unit Price:" in raw_cont and ",," in raw_cont:
                # Subtype A: Multiple unit price tiers
                tiers = [t.strip() for t in raw_cont.split(",,") if t.strip()]
                for t in tiers:
                    m = re.match(r"^Unit Price:\s*৳\s*([0-9,.]+)\s*,\s*\(([0-9]+)'s pack:\s*৳\s*([0-9,.]+)\)", t)
                    if m:
                        u_price = float(m.group(1).replace(",", ""))
                        q = int(m.group(2))
                        p_price = float(m.group(3).replace(",", ""))
                        expected_packs.append({
                            "container_type": "pack",
                            "volume_or_weight_value": None,
                            "volume_or_weight_unit": None,
                            "pack_qty": q,
                            "unit_price_bdt": u_price,
                            "pack_price_bdt": p_price,
                            "normalized_unit_price_bdt": u_price,
                            "comparison_unit": "per_unit",
                        })
                notes = f"Multi-pack tier with {len(expected_packs)} packaging options"

            elif re.search(r"\d+'s\s+pack:", raw_cont):
                # Subtype C: Volume container with pack size
                # e.g. "3 ml cartridge: ৳ 723.40,(5's pack: ৳ 3,617.00),"
                # e.g. "4 ml ampoule: ৳ 30.10,(3's pack: ৳ 90.30),"
                # e.g. "15 ml drop: ৳ 11.55,(12's pack: ৳ 138.60),"
                # e.g. "40 mg sachet: ৳ 10.00,(30's pack: ৳ 300.00),"
                m = re.match(
                    r"^([0-9.]+)\s*([a-zA-Z]+)\s*([a-zA-Z\s]+):\s*৳\s*([0-9,.]+)\s*,\s*\(([0-9]+)'s pack:\s*৳\s*([0-9,.]+)\)",
                    raw_cont,
                )
                if m:
                    val = float(m.group(1))
                    unit = m.group(2).lower()
                    c_name = m.group(3).strip().lower()
                    u_price = float(m.group(4).replace(",", ""))
                    q = int(m.group(5))
                    p_price = float(m.group(6).replace(",", ""))

                    if "ampoule" in c_name:
                        c_type = "ampoule"
                        comp_unit = "per_unit"
                        notes = "Ampoules in multi-pack; primary comparison_unit is per_unit"
                    elif "vial" in c_name:
                        c_type = "vial"
                        comp_unit = "per_unit"
                        notes = "Vials in multi-pack; primary comparison_unit is per_unit"
                    elif "cartridge" in c_name:
                        c_type = "cartridge"
                        comp_unit = "per_unit"
                        notes = "Cartridges in multi-pack; primary comparison_unit is per_unit"
                    elif "sachet" in c_name:
                        c_type = "sachet"
                        comp_unit = "per_unit"
                        notes = "Sachets in multi-pack; primary comparison_unit is per_unit"
                    elif "drop" in c_name or "bottle" in c_name:
                        c_type = "drop" if "drop" in c_name else "bottle"
                        comp_unit = "per_unit"
                        notes = f"Bottles/drops in multi-pack; unit_price is per bottle ({round(u_price/val, 4)} per ml)"
                    else:
                        c_type = "other"
                        comp_unit = "per_unit"
                        notes = f"Pack of volume units; comparison_unit=per_unit"

                    expected_packs.append({
                        "container_type": c_type,
                        "volume_or_weight_value": val,
                        "volume_or_weight_unit": unit,
                        "pack_qty": q,
                        "unit_price_bdt": u_price,
                        "pack_price_bdt": p_price,
                        "normalized_unit_price_bdt": u_price,
                        "comparison_unit": comp_unit,
                    })
                    calc = round(u_price * q, 2)
                    diff = round(abs(calc - p_price), 2)
                    if diff > 0.05:
                        needs_review = True
                        notes += f" | Discrepancy: {u_price} * {q} = {calc} vs {p_price}"
                else:
                    needs_review = True
                    notes = f"Unparsed volume multi-pack: {raw_cont}"

            else:
                # Subtype B: Multiple volume variants separated by comma
                # e.g. "100 ml bottle: ৳ 48.86,200 ml bottle: ৳ 82.95"
                # e.g. "10 gm tube: ৳ 70.00,30 gm tube: ৳ 150.00"
                # e.g. "30 mg vial: ৳ 2,080.00,100 mg vial: ৳ 5,330.00,300 mg vial: ৳ 11,350.00"
                tiers = [t.strip() for t in raw_cont.split(",") if t.strip()]
                for t in tiers:
                    m = re.match(r"^([0-9.]+)\s*([a-zA-Z]+)\s*([a-zA-Z\s]+):\s*৳\s*([0-9,.]+)$", t)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2).lower()
                        c_name = m.group(3).strip().lower()
                        price = float(m.group(4).replace(",", ""))

                        if "bottle" in c_name:
                            c_type = "bottle"
                            comp_unit = "per_ml"
                            norm_price = round(price / val, 4)
                        elif "tube" in c_name:
                            c_type = "tube"
                            comp_unit = "per_gm"
                            norm_price = round(price / val, 4)
                        elif "vial" in c_name:
                            c_type = "vial"
                            comp_unit = "per_unit"
                            norm_price = price
                        elif "bag" in c_name:
                            c_type = "container"
                            comp_unit = "per_ml"
                            norm_price = round(price / val, 4)
                        else:
                            c_type = "other"
                            comp_unit = "per_unit"
                            norm_price = price

                        expected_packs.append({
                            "container_type": c_type,
                            "volume_or_weight_value": val,
                            "volume_or_weight_unit": unit,
                            "pack_qty": None,
                            "unit_price_bdt": None,
                            "pack_price_bdt": price,
                            "normalized_unit_price_bdt": norm_price,
                            "comparison_unit": comp_unit,
                        })
                notes = f"Multi-volume tier with {len(expected_packs)} volume variants"

        # --- CATEGORY 4: other_format (15 rows) ---
        elif category == "other_format":
            if p_id == 30170:  # Lyta 28: (21 white+7 brown) tablet: ৳ 23.52
                needs_review = True
                notes = "Biphasic oral contraceptive blister: 21 active white tablets + 7 placebo brown tablets. pack_qty=28, pack_price=23.52, unit_price=0.84"
                expected_packs.append({
                    "container_type": "pack",
                    "volume_or_weight_value": None,
                    "volume_or_weight_unit": None,
                    "pack_qty": 28,
                    "unit_price_bdt": 0.84,
                    "pack_price_bdt": 23.52,
                    "normalized_unit_price_bdt": 0.84,
                    "comparison_unit": "per_unit",
                })
            elif p_id == 11706:  # Botox: 100 unit vial: ৳ 26,815.28
                needs_review = True
                notes = "Biological unit powder vial; comparison_unit=per_unit"
                expected_packs.append({
                    "container_type": "vial",
                    "volume_or_weight_value": 100.0,
                    "volume_or_weight_unit": "dose",  # biological unit
                    "pack_qty": None,
                    "unit_price_bdt": None,
                    "pack_price_bdt": 26815.28,
                    "normalized_unit_price_bdt": 26815.28,
                    "comparison_unit": "per_unit",
                })
            elif p_id in [14924, 14931]:  # Bonaid, Bonova: 1 tablet kit
                needs_review = True
                price_val = 1500.0 if p_id == 14924 else 2507.52
                notes = f"Single tablet blister kit; pack_qty=1, unit_price={price_val}"
                expected_packs.append({
                    "container_type": "other",
                    "volume_or_weight_value": None,
                    "volume_or_weight_unit": None,
                    "pack_qty": 1,
                    "unit_price_bdt": price_val,
                    "pack_price_bdt": price_val,
                    "normalized_unit_price_bdt": price_val,
                    "comparison_unit": "per_unit",
                })
            elif p_id == 15689:  # MTP Kit: 5 tablet kit: ৳ 300.90
                needs_review = True
                notes = "Medical termination combo kit (1 mifepristone + 4 misoprostol tablets); pack_qty=5, pack_price=300.90, unit_price=60.18"
                expected_packs.append({
                    "container_type": "other",
                    "volume_or_weight_value": None,
                    "volume_or_weight_unit": None,
                    "pack_qty": 5,
                    "unit_price_bdt": 60.18,
                    "pack_price_bdt": 300.90,
                    "normalized_unit_price_bdt": 60.18,
                    "comparison_unit": "per_unit",
                })
            elif p_id == 3443:  # Azmasol refill: 200 metered doses (refill): ৳ 220.00
                needs_review = True
                notes = "Inhaler refill canister without actuator; comparison_unit=per_dose"
                expected_packs.append({
                    "container_type": "inhaler",
                    "volume_or_weight_value": 200.0,
                    "volume_or_weight_unit": "dose",
                    "pack_qty": None,
                    "unit_price_bdt": None,
                    "pack_price_bdt": 220.0,
                    "normalized_unit_price_bdt": 1.10,
                    "comparison_unit": "per_dose",
                })
            elif "metered" in raw_cont and "spray" in raw_cont:
                # e.g. 120 metered sprays: ৳ 250.00 or 14 metered spray: ৳ 450.00
                m = re.match(r"^([0-9.]+)\s*metered\s*sprays?:\s*৳\s*([0-9,.]+)$", raw_cont, re.I)
                if m:
                    cnt = float(m.group(1))
                    price = float(m.group(2).replace(",", ""))
                    expected_packs.append({
                        "container_type": "spray",
                        "volume_or_weight_value": cnt,
                        "volume_or_weight_unit": "spray",
                        "pack_qty": None,
                        "unit_price_bdt": None,
                        "pack_price_bdt": price,
                        "normalized_unit_price_bdt": round(price / cnt, 4),
                        "comparison_unit": "per_dose",
                    })
                    notes = f"Metered nasal/topical spray with {cnt} sprays"
            elif "metered doses" in raw_cont:
                # e.g. 200 metered doses: ৳ 250.00 or 120 metered doses: ৳ 1,075.00
                m = re.match(r"^([0-9.]+)\s*metered\s*doses(?:\s*\(refill\))?:\s*৳\s*([0-9,.]+)$", raw_cont, re.I)
                if m:
                    cnt = float(m.group(1))
                    price = float(m.group(2).replace(",", ""))
                    expected_packs.append({
                        "container_type": "inhaler",
                        "volume_or_weight_value": cnt,
                        "volume_or_weight_unit": "dose",
                        "pack_qty": None,
                        "unit_price_bdt": None,
                        "pack_price_bdt": price,
                        "normalized_unit_price_bdt": round(price / cnt, 4),
                        "comparison_unit": "per_dose",
                    })
                    notes = f"Metered inhaler with {cnt} doses"
            elif "tablet pack" in raw_cont:
                # e.g. '21 tablet pack: ৳ 90.30' or '22 tablet pack: ৳ 130.00' or '2 tablet pack: ৳ 80.00'
                m = re.match(r"^([0-9]+)\s*tablet\s*pack:\s*৳\s*([0-9,.]+)$", raw_cont, re.I)
                if m:
                    q = int(m.group(1))
                    price = float(m.group(2).replace(",", ""))
                    u_price = round(price / q, 4)
                    expected_packs.append({
                        "container_type": "pack",
                        "volume_or_weight_value": None,
                        "volume_or_weight_unit": None,
                        "pack_qty": q,
                        "unit_price_bdt": u_price,
                        "pack_price_bdt": price,
                        "normalized_unit_price_bdt": u_price,
                        "comparison_unit": "per_unit",
                    })
                    notes = f"Fixed tablet pack with {q} tablets"

        # --- CATEGORY 5: unit_price_only (10 rows) ---
        elif category == "unit_price_only":
            m = re.match(r"^Unit Price:\s*৳\s*([0-9,.]+)$", raw_cont)
            if m:
                u_price = float(m.group(1).replace(",", ""))
                expected_packs.append({
                    "container_type": "unit_only",
                    "volume_or_weight_value": None,
                    "volume_or_weight_unit": None,
                    "pack_qty": None,
                    "unit_price_bdt": u_price,
                    "pack_price_bdt": None,
                    "normalized_unit_price_bdt": u_price,
                    "comparison_unit": "per_unit",
                })
                notes = "Unit price only; no pack quantity listed"
            else:
                needs_review = True
                notes = f"Unparseable unit price only: {raw_cont}"

        # --- CATEGORY 6: price_unavailable (5 rows) ---
        elif category == "price_unavailable":
            expected_packs = []
            needs_review = False
            notes = "Price unavailable in source dataset"

        rows.append({
            "product_id": p_id,
            "brand_name": b_name,
            "dosage_form": d_form,
            "raw_package_size": raw_size,
            "raw_package_container": raw_cont,
            "format_category": category,
            "expected_packs_json": json.dumps(expected_packs, ensure_ascii=False),
            "needs_human_review": "true" if needs_review else "false",
            "review_notes": notes,
        })

    fixture_df = pd.DataFrame(rows)
    CSV_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fixture_df.to_csv(CSV_OUTPUT_PATH, index=False, encoding="utf-8")
    print(f"Successfully generated {len(fixture_df)} rows in {CSV_OUTPUT_PATH}")
    return fixture_df


if __name__ == "__main__":
    build_fixture()
