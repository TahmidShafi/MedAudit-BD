"""Comprehensive unit tests for MedAudit BD price parser, packaging normalizer,
and 3-Band Arithmetic Residual Classifier.
"""

import pytest

from medaudit.parsing.price import (
    ALLOWED_COMPARISON_UNITS,
    ALLOWED_CONTAINER_TYPES,
    _classify_residual,
    parse_price,
)


class TestPriceClassificationAndResidualBands:
    """Tests for the 3-Band Arithmetic Residual Classifier."""

    def test_band_1_exact_match(self):
        band, delta = _classify_residual(unit_price=10.0, pack_qty=30, pack_price=300.0)
        assert band == "BAND_1_EXACT"
        assert delta == 0.0

    def test_band_1_sub_milliround(self):
        band, delta = _classify_residual(unit_price=10.00001, pack_qty=10, pack_price=100.0)
        assert band == "BAND_1_EXACT"
        assert delta <= 0.001

    def test_band_2_ciproaid_rounding_drift(self):
        # 9185 Ciproaid: 15.05 * 20 = 301.00, stated pack price = 300.93, delta = 0.07
        # tolerance = 0.01 * 20 = 0.20 -> BAND_2
        band, delta = _classify_residual(unit_price=15.05, pack_qty=20, pack_price=300.93)
        assert band == "BAND_2_ROUNDING_DRIFT"
        assert delta == 0.07

    def test_band_2_vasopin_rounding_drift(self):
        # 30563 Vasopin: 5.03 * 30 = 150.90, stated pack price = 150.97, delta = 0.07
        band, delta = _classify_residual(unit_price=5.03, pack_qty=30, pack_price=150.97)
        assert band == "BAND_2_ROUNDING_DRIFT"
        assert delta == 0.07

    def test_band_2_melphin_rounding_drift(self):
        # 10349 Melphin: 1.66 * 100 = 166.00, stated pack price = 165.84, delta = 0.16
        band, delta = _classify_residual(unit_price=1.66, pack_qty=100, pack_price=165.84)
        assert band == "BAND_2_ROUNDING_DRIFT"
        assert delta == 0.16

    def test_band_2_pamel_rounding_drift(self):
        # 2157 Pamel: 3.41 * 50 = 170.50, stated pack price = 170.44, delta = 0.06
        band, delta = _classify_residual(unit_price=3.41, pack_qty=50, pack_price=170.44)
        assert band == "BAND_2_ROUNDING_DRIFT"
        assert delta == 0.06

    def test_band_3_hard_discrepancy(self):
        # Unit price 10.0, qty 10, stated pack price 150.0 -> delta = 50.0 > 0.10
        band, delta = _classify_residual(unit_price=10.0, pack_qty=10, pack_price=150.0)
        assert band == "BAND_3_HARD_DISCREPANCY"
        assert delta == 50.0

    def test_band_3_emits_anomaly(self):
        raw = "Unit Price: ৳ 10.00,(10's pack: ৳ 150.00)"
        parsed = parse_price(raw, product_id=99999)
        assert len(parsed.packs) == 1
        assert parsed.packs[0].residual_band == "BAND_3_HARD_DISCREPANCY"
        assert parsed.packs[0].residual_delta == 50.0
        assert len(parsed.anomalies) == 1
        assert parsed.anomalies[0].reason_code == "ARITHMETIC_RESIDUAL_BAND_3"
        assert parsed.anomalies[0].module == "price"
        assert parsed.anomalies[0].product_id == 99999


class TestStandardUnitAndSinglePack:
    """Tests for unit_and_single_pack category."""

    def test_standard_unit_price_with_pack(self):
        raw = "Unit Price: ৳ 700.00,(28's pack: ৳ 19,600.00),"
        parsed = parse_price(raw, product_id=28361)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "pack"
        assert pack.volume_or_weight_value is None
        assert pack.pack_qty == 28
        assert pack.unit_price_bdt == 700.0
        assert pack.pack_price_bdt == 19600.0
        assert pack.normalized_unit_price_bdt == 700.0
        assert pack.comparison_unit == "per_unit"
        assert pack.residual_band == "BAND_1_EXACT"
        assert pack.residual_delta == 0.0

    def test_thousand_separator_in_unit_and_pack(self):
        raw = "Unit Price: ৳ 1,250.50,(10's pack: ৳ 12,505.00)"
        parsed = parse_price(raw)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.unit_price_bdt == 1250.50
        assert pack.pack_price_bdt == 12505.00
        assert pack.normalized_unit_price_bdt == 1250.50

    def test_each_capsule_phrasing(self):
        raw = "Each soft gel capsule: ৳ 6.00,(30's pack: ৳ 180.00),"
        parsed = parse_price(raw)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "pack"
        assert pack.pack_qty == 30
        assert pack.unit_price_bdt == 6.0
        assert pack.pack_price_bdt == 180.0
        assert pack.normalized_unit_price_bdt == 6.0
        assert pack.residual_band == "BAND_1_EXACT"


class TestUnitPriceOnly:
    """Tests for unit_price_only category."""

    def test_unit_price_only(self):
        raw = "Unit Price: ৳ 195.00"
        parsed = parse_price(raw, product_id=25153)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "unit_only"
        assert pack.pack_qty is None
        assert pack.unit_price_bdt == 195.0
        assert pack.pack_price_bdt is None
        assert pack.normalized_unit_price_bdt == 195.0
        assert pack.comparison_unit == "per_unit"
        assert pack.residual_band == "SINGLE_PRICE_NO_PACK_CHECK"
        assert pack.residual_delta is None


class TestVolumeContainerSingle:
    """Tests for volume_container_single category."""

    def test_liquid_bottle_per_ml(self):
        raw = "60 ml bottle: ৳ 70.23"
        parsed = parse_price(raw, product_id=28037)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "bottle"
        assert pack.volume_or_weight_value == 60.0
        assert pack.volume_or_weight_unit == "ml"
        assert pack.pack_price_bdt == 70.23
        assert pack.normalized_unit_price_bdt == 1.1705
        assert pack.comparison_unit == "per_ml"
        assert pack.residual_band == "SINGLE_PRICE_NO_PACK_CHECK"

    def test_topical_tube_per_gm(self):
        raw = "15 gm tube: ৳ 60.00"
        parsed = parse_price(raw, product_id=10014)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "tube"
        assert pack.volume_or_weight_value == 15.0
        assert pack.volume_or_weight_unit == "gm"
        assert pack.pack_price_bdt == 60.0
        assert pack.normalized_unit_price_bdt == 4.0
        assert pack.comparison_unit == "per_gm"

    def test_ophthalmic_drop_per_ml(self):
        raw = "5 ml drop: ৳ 85.00"
        parsed = parse_price(raw, product_id=9658)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "drop"
        assert pack.volume_or_weight_value == 5.0
        assert pack.volume_or_weight_unit == "ml"
        assert pack.pack_price_bdt == 85.0
        assert pack.normalized_unit_price_bdt == 17.0
        assert pack.comparison_unit == "per_ml"

    def test_pen_device_per_unit(self):
        # 3 ml per-filled pen: ৳ 7,150.00 -> comparison_unit = per_unit, normalized = pack_price
        raw = "3 ml per-filled pen: ৳ 7,150.00"
        parsed = parse_price(raw, product_id=5724)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "pen"
        assert pack.volume_or_weight_value == 3.0
        assert pack.volume_or_weight_unit == "ml"
        assert pack.pack_price_bdt == 7150.0
        assert pack.normalized_unit_price_bdt == 7150.0
        assert pack.comparison_unit == "per_unit"

    def test_vial_injection_per_unit(self):
        # 100 ml vial: ৳ 44,700.00 -> comparison_unit = per_unit, normalized = pack_price
        raw = "100 ml vial: ৳ 44,700.00"
        parsed = parse_price(raw, product_id=29603)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "vial"
        assert pack.volume_or_weight_value == 100.0
        assert pack.volume_or_weight_unit == "ml"
        assert pack.pack_price_bdt == 44700.0
        assert pack.normalized_unit_price_bdt == 44700.0
        assert pack.comparison_unit == "per_unit"

    def test_prefilled_syringe_per_unit(self):
        raw = "0.4 ml pre-filled syringe: ৳ 450.00"
        parsed = parse_price(raw, product_id=3194)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "other"
        assert pack.volume_or_weight_value == 0.4
        assert pack.volume_or_weight_unit == "ml"
        assert pack.pack_price_bdt == 450.0
        assert pack.normalized_unit_price_bdt == 450.0
        assert pack.comparison_unit == "per_unit"


    def test_biological_units_vial(self):
        raw = "100 unit vial: ৳ 26,815.28"
        parsed = parse_price(raw, product_id=11706)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "vial"
        assert pack.volume_or_weight_value == 100.0
        assert pack.volume_or_weight_unit == "dose"
        assert pack.pack_price_bdt == 26815.28
        assert pack.normalized_unit_price_bdt == 26815.28
        assert pack.comparison_unit == "per_unit"


class TestMultiPackOrTier:
    """Tests for multi_pack_or_tier category."""

    def test_multi_tier_unit_packs_double_comma(self):
        raw = "Unit Price: ৳ 6.50,(30's pack: ৳ 195.00),,Unit Price: ৳ 6.50,(50's pack: ৳ 325.00),"
        parsed = parse_price(raw, product_id=31491)
        assert len(parsed.packs) == 2
        p1, p2 = parsed.packs
        assert p1.pack_qty == 30
        assert p1.unit_price_bdt == 6.5
        assert p1.pack_price_bdt == 195.0
        assert p1.normalized_unit_price_bdt == 6.5
        assert p2.pack_qty == 50
        assert p2.unit_price_bdt == 6.5
        assert p2.pack_price_bdt == 325.0
        assert p2.normalized_unit_price_bdt == 6.5

    def test_multi_volume_bottles(self):
        raw = "100 ml bottle: ৳ 48.86,200 ml bottle: ৳ 82.95"
        parsed = parse_price(raw, product_id=13372)
        assert len(parsed.packs) == 2
        p1, p2 = parsed.packs
        assert p1.volume_or_weight_value == 100.0
        assert p1.normalized_unit_price_bdt == 0.4886
        assert p1.comparison_unit == "per_ml"
        assert p2.volume_or_weight_value == 200.0
        assert p2.normalized_unit_price_bdt == 0.4148
        assert p2.comparison_unit == "per_ml"

    def test_ampoule_with_multi_pack(self):
        raw = "5 ml ampoule: ৳ 100.00,(5's pack: ৳ 500.00),"
        parsed = parse_price(raw, product_id=15741)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "ampoule"
        assert pack.volume_or_weight_value == 5.0
        assert pack.volume_or_weight_unit == "ml"
        assert pack.pack_qty == 5
        assert pack.unit_price_bdt == 100.0
        assert pack.pack_price_bdt == 500.0
        assert pack.normalized_unit_price_bdt == 100.0
        assert pack.comparison_unit == "per_unit"
        assert pack.residual_band == "BAND_1_EXACT"

    def test_cartridge_with_multi_pack(self):
        raw = "3 ml cartridge: ৳ 723.40,(5's pack: ৳ 3,617.00),"
        parsed = parse_price(raw, product_id=26940)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "cartridge"
        assert pack.volume_or_weight_value == 3.0
        assert pack.pack_qty == 5
        assert pack.unit_price_bdt == 723.4
        assert pack.pack_price_bdt == 3617.0
        assert pack.normalized_unit_price_bdt == 723.4
        assert pack.comparison_unit == "per_unit"


class TestOtherFormats:
    """Tests for other_format category."""

    def test_metered_inhaler(self):
        raw = "200 metered doses: ৳ 250.00"
        parsed = parse_price(raw, product_id=3446)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "inhaler"
        assert pack.volume_or_weight_value == 200.0
        assert pack.volume_or_weight_unit == "dose"
        assert pack.pack_price_bdt == 250.0
        assert pack.normalized_unit_price_bdt == 1.25
        assert pack.comparison_unit == "per_dose"

    def test_metered_inhaler_refill(self):
        raw = "200 metered doses (refill): ৳ 220.00"
        parsed = parse_price(raw, product_id=3443)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "inhaler"
        assert pack.volume_or_weight_value == 200.0
        assert pack.volume_or_weight_unit == "dose"
        assert pack.pack_price_bdt == 220.0
        assert pack.normalized_unit_price_bdt == 1.10
        assert pack.comparison_unit == "per_dose"

    def test_metered_spray(self):
        raw = "120 metered sprays: ৳ 250.00"
        parsed = parse_price(raw, product_id=26618)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "spray"
        assert pack.volume_or_weight_value == 120.0
        assert pack.volume_or_weight_unit == "spray"
        assert pack.pack_price_bdt == 250.0
        assert pack.normalized_unit_price_bdt == 2.0833
        assert pack.comparison_unit == "per_dose"

    def test_contraceptive_blister(self):
        raw = "(21 white+7 brown) tablet: ৳ 23.52"
        parsed = parse_price(raw, product_id=30170)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "pack"
        assert pack.pack_qty == 28
        assert pack.pack_price_bdt == 23.52
        assert pack.unit_price_bdt == 0.84
        assert pack.normalized_unit_price_bdt == 0.84
        assert pack.comparison_unit == "per_unit"

    def test_tablet_kit(self):
        raw = "1 tablet kit: ৳ 1,500.00"
        parsed = parse_price(raw, product_id=14924)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "other"
        assert pack.pack_qty == 1
        assert pack.pack_price_bdt == 1500.0
        assert pack.unit_price_bdt == 1500.0
        assert pack.normalized_unit_price_bdt == 1500.0
        assert pack.comparison_unit == "per_unit"

    def test_multi_tablet_kit(self):
        raw = "5 tablet kit: ৳ 300.90"
        parsed = parse_price(raw, product_id=15689)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "other"
        assert pack.pack_qty == 5
        assert pack.pack_price_bdt == 300.90
        assert pack.unit_price_bdt == 60.18
        assert pack.normalized_unit_price_bdt == 60.18
        assert pack.comparison_unit == "per_unit"

    def test_discrete_tablet_pack_single_price(self):
        raw = "22 tablet pack: ৳ 130.00"
        parsed = parse_price(raw, product_id=6112)
        assert len(parsed.packs) == 1
        pack = parsed.packs[0]
        assert pack.container_type == "pack"
        assert pack.pack_qty == 22
        assert pack.pack_price_bdt == 130.0
        assert pack.unit_price_bdt == 5.9091
        assert pack.normalized_unit_price_bdt == 5.9091
        assert pack.comparison_unit == "per_unit"


class TestPriceUnavailableAndFallbacks:
    """Tests for missing prices and fallbacks."""

    def test_price_unavailable_literal(self):
        parsed = parse_price("Price Unavailable", product_id=32398)
        assert len(parsed.packs) == 0
        assert len(parsed.anomalies) == 1
        assert parsed.anomalies[0].reason_code == "PRICE_UNAVAILABLE"

    def test_none_input_with_package_size_fallback(self):
        # container is None, but package size is (50's pack: ৳ 500.00)
        parsed = parse_price(None, raw_package_size="(50's pack: ৳ 500.00)", product_id=123)
        assert len(parsed.packs) == 1
        assert parsed.packs[0].pack_qty == 50
        assert parsed.packs[0].pack_price_bdt == 500.0
        assert parsed.packs[0].unit_price_bdt == 10.0

    def test_both_none_returns_empty(self):
        parsed = parse_price(None, None, product_id=456)
        assert len(parsed.packs) == 0
        assert len(parsed.anomalies) == 0  # pure missing container with no raw string
