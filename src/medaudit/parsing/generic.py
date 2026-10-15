"""Generic formulation parser for MedAudit BD.

Handles compound generic splitting on '+', bracketed annotation extraction,
chemical salt/ester/hydrate radical separation, and BP-to-INN synonym normalization.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from medaudit.parsing.models import GenericComponent, ParseAnomaly, ParsedGeneric

# Documented BP-to-INN and USAN-to-INN synonym map
BP_TO_INN_SYNONYMS: Dict[str, str] = {
    # Analgesics & Antipyretics
    "acetaminophen": "paracetamol",
    "paracetamol": "paracetamol",
    # Diuretics
    "frusemide": "furosemide",
    "furosemide": "furosemide",
    # Antibacterials & Antimicrobials
    "amoxycillin": "amoxicillin",
    "amoxicillin": "amoxicillin",
    "cephalexin": "cefalexin",
    "cefalexin": "cefalexin",
    "cephradine": "cefradine",
    "cefradine": "cefradine",
    "cephadroxil": "cefadroxil",
    "cefadroxil": "cefadroxil",
    "sulphamethoxazole": "sulfamethoxazole",
    "sulfamethoxazole": "sulfamethoxazole",
    "doxycyclin": "doxycycline",
    "doxycycline": "doxycycline",
    "rifampin": "rifampicin",
    "rifampicin": "rifampicin",
    # Bronchodilators & Adrenergics
    "albuterol": "salbutamol",
    "salbutamol": "salbutamol",
    "levalbuterol": "levosalbutamol",
    "levosalbutamol": "levosalbutamol",
    "adrenaline": "epinephrine",
    "epinephrine": "epinephrine",
    "noradrenaline": "norepinephrine",
    "norepinephrine": "norepinephrine",
    "isoprenaline": "isoproterenol",
    # Hypoglycemics
    "glyburide": "glibenclamide",
    "glibenclamide": "glibenclamide",
    # Immunosuppressants
    "cyclosporine": "ciclosporin",
    "cyclosporin": "ciclosporin",
    "ciclosporin": "ciclosporin",
    # Hormones
    "oestrogen": "estrogen",
    "estrogen": "estrogen",
    "oestradiol": "estradiol",
    "estradiol": "estradiol",
    "oestriol": "estriol",
    "estriol": "estriol",
    # Antihistamines
    "chlorpheniramine": "chlorphenamine",
    "chlorphenamine": "chlorphenamine",
    # Antimalarials & Miscellaneous
    "hydroxychloroquin": "hydroxychloroquine",
    "hydroxychloroquine": "hydroxychloroquine",
    "thyroxine": "levothyroxine",
    "levothyroxine": "levothyroxine",
    "clomiphene": "clomifene",
    "clomifene": "clomifene",
}

# 31+ chemical salt, ester, and hydrate radicals identified in Phase 0 spike
# Ordered by length descending so multi-word radicals (e.g. 'sodium phosphate') match first.
SALT_RADICALS: List[str] = sorted(
    [
        "dihydrochloride",
        "hydrochloride",
        "hcl",
        "disodium",
        "trisodium",
        "dipotassium",
        "sodium phosphate",
        "potassium phosphate",
        "sodium succinate",
        "dipropionate",
        "diacetate",
        "sodium",
        "potassium",
        "maleate",
        "sulfate",
        "sulphate",
        "bisulfate",
        "bisulphate",
        "phosphate",
        "diphosphate",
        "acetate",
        "citrate",
        "tartrate",
        "bitartrate",
        "besylate",
        "besilate",
        "mesylate",
        "mesilate",
        "fumarate",
        "calcium",
        "succinate",
        "bromide",
        "hydrobromide",
        "chloride",
        "nitrate",
        "propionate",
        "valerate",
        "butyrate",
        "pivalate",
        "trihydrate",
        "dihydrate",
        "monohydrate",
        "heptahydrate",
        "hexahydrate",
        "anhydrous",
        "axetil",
        "gluconate",
        "lactate",
        "carbonate",
        "aspartate",
        "stearate",
        "decanoate",
        "undecanoate",
        "cypionate",
        "enanthate",
        "furoate",
        "benzoate",
        "tosylate",
        "hyclate",
    ],
    key=len,
    reverse=True,
)

# Preserved chemical entities where metal/salt radical IS the core active moiety
# (e.g., normal saline 'sodium chloride', antacid 'sodium bicarbonate', calcium supplement 'calcium carbonate')
PRESERVED_ACTIVE_MINERALS: Set[str] = {
    "sodium chloride",
    "potassium chloride",
    "calcium carbonate",
    "sodium bicarbonate",
    "zinc sulfate",
    "zinc sulphate",
    "ferrous fumarate",
    "ferrous sulfate",
    "ferrous sulphate",
    "ferrous ascorbate",
    "magnesium hydroxide",
    "aluminium hydroxide",
    "aluminum hydroxide",
    "sodium alginate",
    "potassium bicarbonate",
    "calcium citrate",
    "magnesium carbonate",
    "sodium citrate",
    "sodium lactate",
    "calcium lactate gluconate",
    "iron polymaltose complex",
    "iron hydroxide polymaltose",
    "iron polymaltose",
    "zinc gluconate",
    "magnesium trisilicate",
    "calcium folinate",
    "sodium hyaluronate",
    "sodium carboxymethylcellulose",
    "potassium citrate",
    "calcium acetate",
    "calcium gluconate",
    "potassium nitrate",
}


def _extract_annotations(text: str) -> Tuple[str, Optional[str]]:
    """Extract and remove bracketed annotations [tag] and (tag).
    
    Returns clean core text and combined annotation string.
    """
    annotations: List[str] = []
    
    # Square brackets [tag]
    for match in re.findall(r"\[(.*?)\]", text):
        ann = match.strip()
        if ann:
            annotations.append(ann)
            
    # Round parentheses (tag)
    for match in re.findall(r"\((.*?)\)", text):
        ann = match.strip()
        if ann:
            annotations.append(ann)

    # Strip tags from text
    clean_text = re.sub(r"\[.*?\]|\(.*?\)", " ", text)
    clean_text = re.sub(r"[\s\xa0]+", " ", clean_text).strip()
    
    combined_ann = "; ".join(annotations) if annotations else None
    return clean_text, combined_ann


def _extract_salt_and_canonical(clean_name: str) -> Tuple[str, Optional[str]]:
    """Separate chemical salt radical from base active ingredient and apply BP-to-INN mapping.
    
    Returns (canonical_generic, salt).
    """
    core = clean_name.lower().strip()
    if not core:
        return "", None

    # Check preserved active minerals (e.g. sodium chloride, zinc sulfate monohydrate)
    for mineral in PRESERVED_ACTIVE_MINERALS:
        if core == mineral:
            return BP_TO_INN_SYNONYMS.get(core, core), None
        if core.startswith(mineral + " "):
            # Suffix might be a hydrate (e.g. 'monohydrate')
            trailing = core[len(mineral):].strip()
            return BP_TO_INN_SYNONYMS.get(mineral, mineral), trailing

    # Check trailing salt radical
    found_salt: Optional[str] = None
    canonical_cand = core

    for salt in SALT_RADICALS:
        # Match salt as trailing token: \b{salt}$
        pattern = r"\b" + re.escape(salt) + r"$"
        if re.search(pattern, canonical_cand):
            remainder = re.sub(pattern, "", canonical_cand).strip()
            # If removing salt leaves nothing (e.g. generic was literally 'calcium' alone),
            # do not strip; the salt token IS the active ingredient!
            if remainder:
                found_salt = salt
                canonical_cand = remainder
                break

    # If no trailing salt, check leading metal radical (e.g. 'potassium clavulanate')
    if not found_salt:
        for salt in ["potassium", "sodium"]:
            pattern = r"^" + re.escape(salt) + r"\b"
            if re.search(pattern, canonical_cand):
                remainder = re.sub(pattern, "", canonical_cand).strip()
                if remainder:
                    found_salt = salt
                    canonical_cand = remainder
                    break

    # Apply BP-to-INN synonym normalization
    canonical = BP_TO_INN_SYNONYMS.get(canonical_cand, canonical_cand)
    return canonical, found_salt


def parse_generic(raw_generic: Optional[str], product_id: Optional[int] = None) -> ParsedGeneric:
    """Parse raw generic formulation string into structured ParsedGeneric model.
    
    Splits compound generic on '+', extracts bracketed annotations, separates salts,
    applies BP-to-INN synonyms, and logs structured parse anomalies.
    """
    if raw_generic is None:
        return ParsedGeneric(
            raw_generic=None,
            components=[],
            is_compound=False,
            anomalies=[
                ParseAnomaly(
                    product_id=product_id,
                    module="generic",
                    reason_code="MISSING_GENERIC",
                    raw_string=None,
                    details="Generic active ingredient field is null",
                )
            ],
        )

    clean_raw = re.sub(r"[\s\xa0]+", " ", str(raw_generic)).strip()
    if not clean_raw or clean_raw.lower() == "nan":
        return ParsedGeneric(
            raw_generic=raw_generic,
            components=[],
            is_compound=False,
            anomalies=[
                ParseAnomaly(
                    product_id=product_id,
                    module="generic",
                    reason_code="MISSING_GENERIC",
                    raw_string=str(raw_generic),
                    details="Generic active ingredient string is empty or whitespace",
                )
            ],
        )

    # Check for compound formulation
    raw_components = clean_raw.split("+")
    is_compound = len(raw_components) > 1

    components: List[GenericComponent] = []
    anomalies: List[ParseAnomaly] = []

    for order, raw_part in enumerate(raw_components, 1):
        untrimmed = raw_part
        trimmed = raw_part.strip()

        if not trimmed:
            anomalies.append(
                ParseAnomaly(
                    product_id=product_id,
                    module="generic",
                    reason_code="EMPTY_COMPONENT",
                    raw_string=clean_raw,
                    details=f"Compound generic component at index {order} is empty",
                )
            )
            continue

        # Extract bracketed annotations
        clean_name, annotation = _extract_annotations(trimmed)

        if not clean_name:
            anomalies.append(
                ParseAnomaly(
                    product_id=product_id,
                    module="generic",
                    reason_code="EMPTY_COMPONENT",
                    raw_string=trimmed,
                    details=f"Component at index {order} contains only bracketed tags without drug name",
                )
            )
            continue

        # Extract salt radical and apply INN synonym mapping
        canonical_name, salt = _extract_salt_and_canonical(clean_name)

        if not canonical_name:
            anomalies.append(
                ParseAnomaly(
                    product_id=product_id,
                    module="generic",
                    reason_code="UNPARSEABLE_TOKEN",
                    raw_string=trimmed,
                    details=f"Failed to extract canonical generic moiety from component at index {order}",
                )
            )
            continue

        comp = GenericComponent(
            component_order=order,
            raw_component=trimmed,
            canonical_generic=canonical_name,
            salt=salt,
            annotation=annotation,
            is_nti=False,
        )
        components.append(comp)

    return ParsedGeneric(
        raw_generic=raw_generic,
        components=components,
        is_compound=is_compound,
        anomalies=anomalies,
    )
