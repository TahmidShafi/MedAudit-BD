"""Deterministic Pharmaceutical Phonetic Canonicalizer.

Zero-dependency canonicalizer designed specifically for brand-name and generic
pharmaceutical lexical matching without 4-character Soundex truncation.
"""

from __future__ import annotations

import re


def pharma_phonetic(word: str) -> str:
    """Compute pharmaceutical phonetic canonical key.

    Rules applied:
    1. Lowercase and strip all non-alphabetic characters.
    2. Normalize pharmaceutical digraphs and letter substitutions:
       - ph -> f
       - ch -> k
       - rh -> r
       - th -> t
       - c before e, i, y -> s
       - c -> k
       - q -> k
       - x -> z
       - y -> i
    3. Drop silent 'h' after consonants (e.g. gh, bh, dh, kh).
    4. Collapse consecutive identical letters.
    5. Strip all vowels ('a', 'e', 'i', 'o', 'u') EXCEPT the very first character.
    6. Final collapse of consecutive identical letters.

    Args:
        word: Raw brand or generic medicine name string.

    Returns:
        Canonical phonetic key string (arbitrary length, not truncated to 4 chars).
    """
    if not word:
        return ""

    # 1. Lowercase and strip non-alphabetic characters
    s = re.sub(r"[^a-z]", "", word.lower())
    if not s:
        return ""

    # 2. Digraphs and consonant normalizations
    s = s.replace("ph", "f")
    s = s.replace("ch", "k")
    s = s.replace("rh", "r")
    s = s.replace("th", "t")
    s = re.sub(r"c(?=[eiy])", "s", s)
    s = s.replace("c", "k")
    s = s.replace("q", "k")
    s = s.replace("x", "z")
    s = s.replace("y", "i")

    # 3. Drop silent 'h' after consonants
    s = re.sub(r"([bdfgjklmnprstvwz])h+", r"\1", s)

    # 4. Collapse consecutive identical letters
    s = re.sub(r"(.)\1+", r"\1", s)

    # 5. Strip all vowels EXCEPT the very first character
    first = s[0]
    rest = re.sub(r"[aeiou]", "", s[1:])
    combined = first + rest

    # 6. Final collapse of consecutive identical letters
    return re.sub(r"(.)\1+", r"\1", combined)
