"""MedAudit BD prescription auditing package."""

from medaudit.audit.alternatives import find_same_generic_alternatives
from medaudit.audit.duplicates import check_duplicate_active_ingredients
from medaudit.audit.engine import audit_prescription
from medaudit.audit.nti import CONSERVATIVE_NTI_GENERICS, get_nti_badge, is_nti_generic
from medaudit.audit.release_type import (
    check_catalog_shelf_10x_hazards,
    check_intra_prescription_release_and_strength_hazards,
    detect_release_type,
)
from medaudit.audit.search import resolve_prescribed_item, search_products

__all__ = [
    "CONSERVATIVE_NTI_GENERICS",
    "audit_prescription",
    "check_catalog_shelf_10x_hazards",
    "check_duplicate_active_ingredients",
    "check_intra_prescription_release_and_strength_hazards",
    "detect_release_type",
    "find_same_generic_alternatives",
    "get_nti_badge",
    "is_nti_generic",
    "resolve_prescribed_item",
    "search_products",
]
