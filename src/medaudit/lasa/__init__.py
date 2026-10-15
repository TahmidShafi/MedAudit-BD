"""MedAudit BD Look-Alike Sound-Alike (LASA) module."""

from medaudit.lasa.candidates import BrandCandidate, extract_prefix_and_stem, load_brand_candidates
from medaudit.lasa.phonetic import pharma_phonetic
from medaudit.lasa.tiers import (
    LASAPair,
    check_intra_prescription_lasa_hazards,
    compute_lasa_pairs,
    generate_diff_preview,
    get_lasa_warnings_for_brand,
    save_lasa_pairs_to_db,
)

__all__ = [
    "pharma_phonetic",
    "BrandCandidate",
    "extract_prefix_and_stem",
    "load_brand_candidates",
    "LASAPair",
    "compute_lasa_pairs",
    "generate_diff_preview",
    "save_lasa_pairs_to_db",
    "get_lasa_warnings_for_brand",
    "check_intra_prescription_lasa_hazards",
]
