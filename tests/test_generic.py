"""Unit tests for src/medaudit/parsing/generic.py."""

import pytest

from medaudit.parsing.generic import parse_generic
from medaudit.parsing.models import ParsedGeneric


def test_parse_simple_generic_without_salt():
    res = parse_generic("Paracetamol")
    assert res.is_valid
    assert not res.is_compound
    assert len(res.components) == 1
    comp = res.components[0]
    assert comp.component_order == 1
    assert comp.canonical_generic == "paracetamol"
    assert comp.salt is None
    assert comp.annotation is None


def test_parse_generic_with_trailing_salt():
    res = parse_generic("Metformin Hydrochloride")
    assert res.is_valid
    assert len(res.components) == 1
    comp = res.components[0]
    assert comp.canonical_generic == "metformin"
    assert comp.salt == "hydrochloride"


def test_parse_generic_with_multi_word_salt():
    res = parse_generic("Betamethasone Sodium Phosphate")
    assert res.is_valid
    assert len(res.components) == 1
    comp = res.components[0]
    assert comp.canonical_generic == "betamethasone"
    assert comp.salt == "sodium phosphate"


def test_parse_generic_with_ester_radical():
    res = parse_generic("Cefuroxime Axetil")
    assert res.is_valid
    comp = res.components[0]
    assert comp.canonical_generic == "cefuroxime"
    assert comp.salt == "axetil"


def test_parse_generic_with_besilate_salt():
    res = parse_generic("Amlodipine Besilate")
    assert res.is_valid
    comp = res.components[0]
    assert comp.canonical_generic == "amlodipine"
    assert comp.salt == "besilate"


def test_parse_generic_with_hydrate_radical():
    res = parse_generic("Amoxicillin Trihydrate")
    assert res.is_valid
    comp = res.components[0]
    assert comp.canonical_generic == "amoxicillin"
    assert comp.salt == "trihydrate"


def test_parse_compound_generic_two_components():
    res = parse_generic("Linagliptin + Metformin Hydrochloride")
    assert res.is_valid
    assert res.is_compound
    assert len(res.components) == 2

    c1 = res.components[0]
    assert c1.component_order == 1
    assert c1.raw_component == "Linagliptin"
    assert c1.canonical_generic == "linagliptin"
    assert c1.salt is None

    c2 = res.components[1]
    assert c2.component_order == 2
    assert c2.raw_component == "Metformin Hydrochloride"
    assert c2.canonical_generic == "metformin"
    assert c2.salt == "hydrochloride"

    assert res.canonical_formula == "linagliptin + metformin"


def test_parse_compound_generic_three_components():
    res = parse_generic("Aluminium Hydroxide + Magnesium Hydroxide + Simethicone")
    assert res.is_valid
    assert res.is_compound
    assert len(res.components) == 3
    assert res.components[0].canonical_generic == "aluminium hydroxide"
    assert res.components[1].canonical_generic == "magnesium hydroxide"
    assert res.components[2].canonical_generic == "simethicone"


def test_parse_preserved_mineral_sodium_chloride():
    res = parse_generic("Sodium Chloride")
    assert res.is_valid
    comp = res.components[0]
    # Sodium is NOT stripped because sodium chloride is an active electrolyte
    assert comp.canonical_generic == "sodium chloride"
    assert comp.salt is None


def test_parse_preserved_mineral_with_hydrate():
    res = parse_generic("Zinc Sulfate Monohydrate")
    assert res.is_valid
    comp = res.components[0]
    # Preserves zinc sulfate and extracts monohydrate
    assert comp.canonical_generic == "zinc sulfate"
    assert comp.salt == "monohydrate"


def test_parse_preserved_mineral_calcium_carbonate():
    res = parse_generic("Calcium Carbonate")
    assert res.is_valid
    assert res.components[0].canonical_generic == "calcium carbonate"
    assert res.components[0].salt is None


def test_parse_square_bracket_annotation():
    res = parse_generic("Calcium Carbonate [Coral source] + Vitamin D3")
    assert res.is_valid
    assert len(res.components) == 2
    assert res.components[0].canonical_generic == "calcium carbonate"
    assert res.components[0].annotation == "Coral source"
    assert res.components[1].canonical_generic == "vitamin d3"
    assert res.components[1].annotation is None


def test_parse_round_parentheses_annotation_pack_info():
    res = parse_generic("Ethinyl Estradiol + Drospirenone (21 tablet)")
    assert res.is_valid
    assert len(res.components) == 2
    assert res.components[0].canonical_generic == "ethinyl estradiol"
    assert res.components[1].canonical_generic == "drospirenone"
    assert res.components[1].annotation == "21 tablet"


def test_parse_round_parentheses_annotation_route():
    res = parse_generic("Betamethasone + Neomycin Sulphate (E/E)")
    assert res.is_valid
    assert len(res.components) == 2
    assert res.components[0].canonical_generic == "betamethasone"
    assert res.components[1].canonical_generic == "neomycin"
    assert res.components[1].salt == "sulphate"
    assert res.components[1].annotation == "E/E"


def test_parse_round_parentheses_annotation_intravenous():
    res = parse_generic("Sodium Chloride (Intravenous Solution)")
    assert res.is_valid
    assert res.components[0].canonical_generic == "sodium chloride"
    assert res.components[0].annotation == "Intravenous Solution"


def test_parse_non_breaking_spaces_handling():
    res = parse_generic("Paracetamol\xa0+\xa0Tramadol\xa0Hydrochloride")
    assert res.is_valid
    assert len(res.components) == 2
    assert res.components[0].canonical_generic == "paracetamol"
    assert res.components[1].canonical_generic == "tramadol"
    assert res.components[1].salt == "hydrochloride"


def test_bp_to_inn_synonym_acetaminophen_to_paracetamol():
    res = parse_generic("Acetaminophen")
    assert res.is_valid
    assert res.components[0].canonical_generic == "paracetamol"


def test_bp_to_inn_synonym_frusemide_to_furosemide():
    res = parse_generic("Frusemide")
    assert res.is_valid
    assert res.components[0].canonical_generic == "furosemide"


def test_bp_to_inn_synonym_amoxycillin_to_amoxicillin():
    res = parse_generic("Amoxycillin Trihydrate")
    assert res.is_valid
    assert res.components[0].canonical_generic == "amoxicillin"
    assert res.components[0].salt == "trihydrate"


def test_bp_to_inn_synonym_cephalexin_to_cefalexin():
    res = parse_generic("Cephalexin")
    assert res.is_valid
    assert res.components[0].canonical_generic == "cefalexin"


def test_bp_to_inn_synonym_albuterol_to_salbutamol():
    res = parse_generic("Albuterol Sulfate")
    assert res.is_valid
    assert res.components[0].canonical_generic == "salbutamol"
    assert res.components[0].salt == "sulfate"


def test_bp_to_inn_synonym_adrenaline_to_epinephrine():
    res = parse_generic("Adrenaline")
    assert res.is_valid
    assert res.components[0].canonical_generic == "epinephrine"


def test_bp_to_inn_synonym_cyclosporine_to_ciclosporin():
    res = parse_generic("Cyclosporine")
    assert res.is_valid
    assert res.components[0].canonical_generic == "ciclosporin"


def test_bp_to_inn_synonym_glyburide_to_glibenclamide():
    res = parse_generic("Glyburide")
    assert res.is_valid
    assert res.components[0].canonical_generic == "glibenclamide"


def test_parse_generic_missing_null():
    res = parse_generic(None, product_id=403)
    assert not res.is_valid
    assert len(res.components) == 0
    assert len(res.anomalies) == 1
    assert res.anomalies[0].reason_code == "MISSING_GENERIC"
    assert res.anomalies[0].product_id == 403


def test_parse_generic_empty_string():
    res = parse_generic("   ", product_id=500)
    assert not res.is_valid
    assert len(res.anomalies) == 1
    assert res.anomalies[0].reason_code == "MISSING_GENERIC"


def test_parse_generic_empty_component_in_compound():
    res = parse_generic("Paracetamol + + Caffeine")
    assert len(res.anomalies) == 1
    assert res.anomalies[0].reason_code == "EMPTY_COMPONENT"
    # The valid parts still parsed
    assert len(res.components) == 2
    assert res.components[0].canonical_generic == "paracetamol"
    assert res.components[1].canonical_generic == "caffeine"
