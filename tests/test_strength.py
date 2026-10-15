"""Unit tests for src/medaudit/parsing/strength.py."""

import pytest

from medaudit.parsing.models import ParsedStrength
from medaudit.parsing.strength import parse_strength


def test_parse_simple_mass_mg():
    res = parse_strength("500 mg")
    assert res.is_valid
    assert not res.is_compound
    assert len(res.components) == 1
    comp = res.components[0]
    assert comp.component_order == 1
    assert comp.amount == 500.0
    assert comp.amount_unit == "mg"
    assert comp.normalized_mg == 500.0
    assert comp.normalized_concentration_mg_per_ml is None


def test_parse_mass_gm_to_mg_normalization():
    res = parse_strength("1 gm")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 1.0
    assert comp.amount_unit == "gm"
    assert comp.normalized_mg == 1000.0


def test_parse_mass_g_to_mg_normalization():
    res = parse_strength("2.5 g")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 2.5
    assert comp.normalized_mg == 2500.0


def test_parse_mass_mcg_to_mg_normalization():
    res = parse_strength("500 mcg")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 500.0
    assert comp.amount_unit == "mcg"
    assert comp.normalized_mg == 0.5


def test_parse_mass_microgram_symbol():
    res1 = parse_strength("20 \u00b5g")
    assert res1.is_valid
    assert res1.components[0].amount == 20.0
    assert res1.components[0].normalized_mg == 0.02

    res2 = parse_strength("20 \u03bcg")
    assert res2.is_valid
    assert res2.components[0].amount == 20.0
    assert res2.components[0].normalized_mg == 0.02


def test_parse_liquid_concentration_simple():
    res = parse_strength("25 mg/ml")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 25.0
    assert comp.amount_unit == "mg"
    assert comp.denominator_amount == 1.0
    assert comp.denominator_unit == "ml"
    assert comp.normalized_concentration_mg_per_ml == 25.0


def test_parse_liquid_concentration_with_denominator():
    # 125 mg / 5 ml = 25 mg/ml
    res = parse_strength("125 mg/5 ml")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 125.0
    assert comp.amount_unit == "mg"
    assert comp.denominator_amount == 5.0
    assert comp.denominator_unit == "ml"
    assert comp.normalized_concentration_mg_per_ml == 25.0


def test_parse_liquid_concentration_mcg_per_5ml():
    # 500 mcg / 5 ml = 0.5 mg / 5 ml = 0.1 mg/ml
    res = parse_strength("500 mcg/5 ml")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 500.0
    assert comp.amount_unit == "mcg"
    assert comp.normalized_concentration_mg_per_ml == 0.1


def test_parse_percentage():
    # 1% = 10 mg/ml
    res = parse_strength("1%")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 1.0
    assert comp.amount_unit == "%"
    assert comp.normalized_concentration_mg_per_ml == 10.0


def test_parse_percentage_wv():
    # 0.05% w/v = 0.5 mg/ml
    res = parse_strength("0.05% w/v")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 0.05
    assert comp.normalized_concentration_mg_per_ml == 0.5


def test_parse_percentage_vv():
    res = parse_strength("5% v/v")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 5.0
    assert comp.amount_unit == "%"


def test_parse_inhaler_puff_actuation():
    res = parse_strength("100 mcg/puff")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 100.0
    assert comp.amount_unit == "mcg"
    assert comp.denominator_unit == "puff"


def test_parse_nasal_spray():
    res = parse_strength("50 mcg/spray")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 50.0
    assert comp.amount_unit == "mcg"
    assert comp.denominator_unit == "spray"


def test_parse_injectable_vial():
    res = parse_strength("500 mg/vial")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 500.0
    assert comp.denominator_unit == "vial"
    assert comp.normalized_mg == 500.0


def test_parse_injectable_gram_vial():
    res = parse_strength("1 gm/vial")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 1.0
    assert comp.normalized_mg == 1000.0


def test_parse_international_units_iu():
    res = parse_strength("100 IU")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 100.0
    assert comp.amount_unit == "IU"


def test_parse_iu_concentration():
    res = parse_strength("100 IU/ml")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 100.0
    assert comp.amount_unit == "IU"
    assert comp.denominator_unit == "ml"


def test_parse_anti_xa_iu():
    res = parse_strength("8000 Anti-Xa IU/0.8 ml")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 8000.0
    assert "Anti-Xa IU" in comp.amount_unit
    assert comp.denominator_amount == 0.8
    assert comp.denominator_unit == "ml"


def test_parse_miu():
    res = parse_strength("1 MIU")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 1_000_000.0
    assert comp.amount_unit == "IU"


def test_parse_lac_units():
    # 12 lac units = 1,200,000 IU
    res = parse_strength("12 lac units/vial")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 1_200_000.0
    assert comp.amount_unit == "IU"
    assert comp.denominator_unit == "vial"


def test_parse_probiotics_billion_cfu():
    res = parse_strength("4 billion")
    assert res.is_valid
    comp = res.components[0]
    assert comp.amount == 4_000_000_000.0
    assert comp.amount_unit == "CFU"


def test_parse_multi_component_compound():
    res = parse_strength("500 mg + 30 mg")
    assert res.is_valid
    assert res.is_compound
    assert len(res.components) == 2
    assert res.components[0].component_order == 1
    assert res.components[0].amount == 500.0
    assert res.components[0].normalized_mg == 500.0
    assert res.components[1].component_order == 2
    assert res.components[1].amount == 30.0
    assert res.components[1].normalized_mg == 30.0


def test_parse_three_way_compound():
    res = parse_strength("6 mg + 200 mg + 50 mg")
    assert res.is_valid
    assert res.is_compound
    assert len(res.components) == 3
    assert res.components[0].normalized_mg == 6.0
    assert res.components[1].normalized_mg == 200.0
    assert res.components[2].normalized_mg == 50.0


def test_parse_parenthesized_compound_slash_concentration():
    # '(10 mg+30 mg+1.25 mg)/5 ml' -> 3 components, each divided by 5 ml
    res = parse_strength("(10 mg+30 mg+1.25 mg)/5 ml")
    assert res.is_valid
    assert res.is_compound
    assert len(res.components) == 3

    # 10 mg / 5 ml = 2.0 mg/ml
    assert res.components[0].amount == 10.0
    assert res.components[0].normalized_concentration_mg_per_ml == 2.0

    # 30 mg / 5 ml = 6.0 mg/ml
    assert res.components[1].amount == 30.0
    assert res.components[1].normalized_concentration_mg_per_ml == 6.0

    # 1.25 mg / 5 ml = 0.25 mg/ml
    assert res.components[2].amount == 1.25
    assert res.components[2].normalized_concentration_mg_per_ml == 0.25


def test_parse_insulin_biphasic_mixture():
    res = parse_strength("30%+70% in 100 IU/ml")
    assert res.is_valid
    assert res.is_compound
    assert len(res.components) == 2
    assert res.components[0].amount == 30.0  # 30% of 100 IU/ml = 30 IU/ml
    assert res.components[0].amount_unit == "IU/ml"
    assert res.components[1].amount == 70.0  # 70% of 100 IU/ml = 70 IU/ml
    assert res.components[1].amount_unit == "IU/ml"


def test_parse_ampersand_compound():
    res = parse_strength("150 mg & 400 mg")
    assert res.is_valid
    assert res.is_compound
    assert len(res.components) == 2
    assert res.components[0].normalized_mg == 150.0
    assert res.components[1].normalized_mg == 400.0


def test_parse_strength_component_count_mismatch():
    # Generic has 2 components, but strength has 1 component
    res = parse_strength("500 mg", generic_component_count=2, product_id=999)
    assert res.is_valid
    assert len(res.anomalies) == 1
    anom = res.anomalies[0]
    assert anom.reason_code == "COMPONENT_COUNT_MISMATCH"
    assert anom.product_id == 999


def test_parse_strength_missing_null():
    res = parse_strength(None, product_id=123)
    assert not res.is_valid
    assert len(res.components) == 0
    assert len(res.anomalies) == 1
    assert res.anomalies[0].reason_code == "MISSING_STRENGTH"
    assert res.anomalies[0].product_id == 123


def test_parse_strength_empty_string():
    res = parse_strength("   ")
    assert not res.is_valid
    assert len(res.anomalies) == 1
    assert res.anomalies[0].reason_code == "MISSING_STRENGTH"


def test_parse_strength_unparseable_token():
    res = parse_strength("invalid_strength_xyz#@!")
    assert not res.is_valid
    assert len(res.anomalies) == 1
    assert res.anomalies[0].reason_code == "UNPARSEABLE_STRENGTH_TOKEN"
