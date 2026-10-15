"""Narrow Therapeutic Index (NTI) drug detection and substitution locking."""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

# Conservative NTI active ingredient set defined by clinical pharmacology guidelines
CONSERVATIVE_NTI_GENERICS: Set[str] = {
    "warfarin",
    "levothyroxine",
    "phenytoin",
    "digoxin",
    "lithium",
    "carbamazepine",
    "tacrolimus",
    "ciclosporin",
    "theophylline",
    "valproic acid",
    "sodium valproate",
}


def is_nti_generic(generic_name: Optional[str]) -> bool:
    """Check if an active pharmaceutical ingredient belongs to the conservative NTI class.

    Matches all insulin variants (e.g., insulin human, insulin glargine, insulin aspart)
    as well as oral solids in CONSERVATIVE_NTI_GENERICS.
    """
    if not generic_name:
        return False
    g_lower = generic_name.strip().lower()
    if "insulin" in g_lower:
        return True
    return g_lower in CONSERVATIVE_NTI_GENERICS


def get_nti_badge(generic_name: str) -> Optional[Dict[str, Any]]:
    """Generate structured NTI warning badge and substitution lock details."""
    if is_nti_generic(generic_name):
        return {
            "is_nti": True,
            "badge": "NTI_DRUG",
            "substitution_locked": True,
            "explanation": (
                f"Narrow Therapeutic Index drug ({generic_name}): minor differences in dose "
                f"or blood concentration may cause serious therapeutic failures or life-threatening "
                f"adverse reactions. Brand substitution is strictly locked."
            ),
        }
    return None
