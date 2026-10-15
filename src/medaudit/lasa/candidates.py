"""Brand candidate loading, manufacturer prefix extraction, and pairwise distance matrices.

Uses rapidfuzz Damerau-Levenshtein normalized similarity satisfying the triangle inequality,
combined with pharmaceutical phonetic canonicalization.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, FrozenSet, Generator, List, Optional, Tuple

import numpy as np
from rapidfuzz.distance import DamerauLevenshtein
from rapidfuzz.process import cdist

from medaudit.lasa.phonetic import pharma_phonetic


@dataclass(frozen=True)
class BrandCandidate:
    """In-memory representation of a deduplicated brand entity with phonetic and stem properties."""

    brand_id: int
    brand_name: str
    normalized_brand_name: str
    manufacturer: str
    prefix: Optional[str]
    prefix_stem: str
    phonetic_key: str
    stem_phonetic_key: str
    canonical_generics: FrozenSet[str]


def extract_prefix_and_stem(brand_name: str) -> Tuple[Optional[str], str]:
    """Extract manufacturer house prefix token and post-prefix stem.

    Matches hyphenated prefixes such as 'G-', 'A-', 'SB-', 'HI-', 'SK-', 'E-', etc.

    Returns:
        Tuple of (prefix_token or None, post-prefix stem in lowercase).
    """
    clean_name = brand_name.strip()
    m = re.match(r"^([A-Za-z0-9]+)-(.+)$", clean_name)
    if m:
        prefix = m.group(1).upper()
        stem = m.group(2).strip().lower()
        return prefix, stem
    return None, clean_name.lower()


def load_brand_candidates(conn: sqlite3.Connection) -> List[BrandCandidate]:
    """Load all deduplicated brand entities from SQLite along with their active generic sets.

    Args:
        conn: Open SQLite connection to medaudit.db.

    Returns:
        List of BrandCandidate objects sorted by brand_id.
    """
    cursor = conn.cursor()

    # Query all brands
    cursor.execute(
        """
        SELECT brand_id, brand_name, normalized_brand_name, manufacturer, prefix_stem
        FROM brands
        ORDER BY brand_id
        """
    )
    brand_rows = cursor.fetchall()

    # Query canonical generic components per brand
    cursor.execute(
        """
        SELECT p.brand_id, gc.canonical_generic
        FROM products p
        JOIN generic_components gc ON p.product_id = gc.product_id
        """
    )
    gen_rows = cursor.fetchall()
    brand_generics: Dict[int, set[str]] = defaultdict(set)
    for bid, gen in gen_rows:
        brand_generics[bid].add(gen)

    candidates: List[BrandCandidate] = []
    for bid, bname, norm_name, mfg, _ in brand_rows:
        prefix, stem = extract_prefix_and_stem(bname)
        phon_key = pharma_phonetic(norm_name)
        stem_phon_key = pharma_phonetic(stem)
        gen_set = frozenset(brand_generics.get(bid, set()))

        candidates.append(
            BrandCandidate(
                brand_id=bid,
                brand_name=bname,
                normalized_brand_name=norm_name,
                manufacturer=mfg,
                prefix=prefix,
                prefix_stem=stem,
                phonetic_key=phon_key,
                stem_phonetic_key=stem_phon_key,
                canonical_generics=gen_set,
            )
        )

    return candidates


def compute_full_similarity_matrix(strings: List[str]) -> np.ndarray:
    """Compute dense pairwise normalized Damerau-Levenshtein similarity matrix using SIMD cdist.

    Args:
        strings: List of N input strings.

    Returns:
        (N, N) float32 numpy array with normalized similarities in [0.0, 1.0].
    """
    return cdist(
        strings,
        strings,
        scorer=DamerauLevenshtein.normalized_similarity,
        dtype=np.float32,
        workers=-1,
    )


def compute_blocked_candidates(
    strings: List[str],
    min_similarity: float = 0.70,
    block_mode: str = "length",
) -> Generator[Tuple[int, int, float], None, None]:
    """Generate candidate pairs using blocking to avoid full N x N dense matrix allocation.

    Modes:
    - 'length': Blocks pairs where length difference |len(a) - len(b)| / max(len(a), len(b)) <= (1 - min_similarity).
      Guarantees 100% recall of pairs with similarity >= min_similarity.
    - 'first_letter': Blocks by first character of string. Fast and low memory, but sacrifices pairs
      where substitution/insertion occurs at the first character (recall trade-off).

    Yields:
        (i, j, similarity) for pairs with similarity >= min_similarity where i < j.
    """
    n = len(strings)
    if block_mode == "first_letter":
        # Group by initial character
        letter_buckets: Dict[str, List[int]] = defaultdict(list)
        for idx, s in enumerate(strings):
            c = s[0] if s else ""
            letter_buckets[c].append(idx)

        for _, indices in letter_buckets.items():
            if len(indices) < 2:
                continue
            bucket_strings = [strings[idx] for idx in indices]
            sub_mat = cdist(
                bucket_strings,
                bucket_strings,
                scorer=DamerauLevenshtein.normalized_similarity,
                dtype=np.float32,
                workers=-1,
            )
            rows, cols = np.where(
                (sub_mat >= min_similarity) & (np.triu(np.ones(sub_mat.shape, dtype=bool), k=1))
            )
            for r, c in zip(rows, cols):
                orig_i = indices[r]
                orig_j = indices[c]
                if orig_i > orig_j:
                    orig_i, orig_j = orig_j, orig_i
                yield (orig_i, orig_j, float(sub_mat[r, c]))

    elif block_mode == "length":
        # Sort by length for banded execution
        by_len: Dict[int, List[int]] = defaultdict(list)
        for idx, s in enumerate(strings):
            by_len[len(s)].append(idx)

        lengths = sorted(by_len.keys())
        for idx_l1, l1 in enumerate(lengths):
            list1 = by_len[l1]
            # Intra-length comparison
            if len(list1) > 1:
                str_l1 = [strings[i] for i in list1]
                sub_mat = cdist(
                    str_l1,
                    str_l1,
                    scorer=DamerauLevenshtein.normalized_similarity,
                    dtype=np.float32,
                    workers=-1,
                )
                rows, cols = np.where(
                    (sub_mat >= min_similarity) & (np.triu(np.ones(sub_mat.shape, dtype=bool), k=1))
                )
                for r, c in zip(rows, cols):
                    orig_i = list1[r]
                    orig_j = list1[c]
                    if orig_i > orig_j:
                        orig_i, orig_j = orig_j, orig_i
                    yield (orig_i, orig_j, float(sub_mat[r, c]))

            # Inter-length comparison within allowed length delta
            for l2 in lengths[idx_l1 + 1 :]:
                # If length delta exceeds max possible for min_similarity, break
                if (l2 - l1) / l2 > (1.0 - min_similarity):
                    break
                list2 = by_len[l2]
                str_l1 = [strings[i] for i in list1]
                str_l2 = [strings[j] for j in list2]
                sub_mat = cdist(
                    str_l1,
                    str_l2,
                    scorer=DamerauLevenshtein.normalized_similarity,
                    dtype=np.float32,
                    workers=-1,
                )
                rows, cols = np.where(sub_mat >= min_similarity)
                for r, c in zip(rows, cols):
                    orig_i = list1[r]
                    orig_j = list2[c]
                    if orig_i > orig_j:
                        orig_i, orig_j = orig_j, orig_i
                    yield (orig_i, orig_j, float(sub_mat[r, c]))
