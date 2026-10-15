"""Ablation Studies, Clique Analysis, ISMP Calibration, and Runtime Benchmarking.

Evaluates:
1. 4-way prefix ablation matrix (Modes A, B, C, D).
2. Same-manufacturer clique reduction (Mode A vs Mode B).
3. ISMP generic sanity check against 250 random generic pairs (pure Python Mann-Whitney U & ROC-AUC).
4. Runtime and memory benchmark comparing full dense cdist vs blocked cdist.
"""

from __future__ import annotations

import random
import re
import sqlite3
import time
import tracemalloc
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from rapidfuzz.distance import DamerauLevenshtein
from rapidfuzz.process import cdist

from medaudit.config import SEED
from medaudit.lasa.candidates import (
    BrandCandidate,
    compute_blocked_candidates,
    compute_full_similarity_matrix,
    load_brand_candidates,
)
from medaudit.lasa.phonetic import pharma_phonetic
from medaudit.lasa.tiers import classify_generic_overlap, compute_lasa_pairs

# 25 Canonical ISMP Confused Generic Pairs
ISMP_GENERIC_PAIRS: List[Tuple[str, str]] = [
    ("amiodarone", "amlodipine"),
    ("azathioprine", "azithromycin"),
    ("bupropion", "buspirone"),
    ("carbamazepine", "oxcarbazepine"),
    ("carvedilol", "carteolol"),
    ("cefazolin", "ceftriaxone"),
    ("cefixime", "cefotaxime"),
    ("ceftazidime", "ceftriaxone"),
    ("cetirizine", "sertraline"),
    ("chlorpromazine", "chlorpropamide"),
    ("clobazam", "clonazepam"),
    ("clomiphene", "clomipramine"),
    ("clonidine", "klonopin"),
    ("cycloserine", "cyclosporine"),
    ("daunorubicin", "doxorubicin"),
    ("dimenhydrinate", "diphenhydramine"),
    ("dobutamine", "dopamine"),
    ("ephedrine", "epinephrine"),
    ("fluoxetine", "paroxetine"),
    ("glipizide", "glyburide"),
    ("hydralazine", "hydroxyzine"),
    ("lamivudine", "lamotrigine"),
    ("levetiracetam", "levofloxacin"),
    ("metformin", "metronidazole"),
    ("prednisolone", "prednisone"),
]


def compute_distribution_stats(values: List[float]) -> Dict[str, float]:
    """Compute mean, median, Q1, Q3, and IQR for a list of floating point values."""
    if not values:
        return {"mean": 0.0, "median": 0.0, "q1": 0.0, "q3": 0.0, "iqr": 0.0}

    s = sorted(values)
    n = len(s)
    mean_val = sum(s) / n

    def percentile(p: float) -> float:
        k = (n - 1) * p
        f = int(k)
        c = f + 1
        if c < n:
            return s[f] + (k - f) * (s[c] - s[f])
        return s[f]

    q1 = percentile(0.25)
    med = percentile(0.50)
    q3 = percentile(0.75)
    iqr = q3 - q1

    return {
        "mean": round(mean_val, 4),
        "median": round(med, 4),
        "q1": round(q1, 4),
        "q3": round(q3, 4),
        "iqr": round(iqr, 4),
    }


def compute_mann_whitney_u_and_auc(
    group1: List[float], group2: List[float]
) -> Tuple[float, float]:
    """Compute exact Mann-Whitney U statistic and ROC-AUC separation in pure Python."""
    n1 = len(group1)
    n2 = len(group2)
    if n1 == 0 or n2 == 0:
        return 0.0, 0.5

    u_stat = 0.0
    for x in group1:
        for y in group2:
            if x > y:
                u_stat += 1.0
            elif x == y:
                u_stat += 0.5

    roc_auc = u_stat / (n1 * n2)
    return u_stat, round(roc_auc, 4)


def find_maximal_clique(adj: Dict[int, Set[int]], nodes: Set[int]) -> List[int]:
    """Find the maximum clique in an undirected graph using the Bron-Kerbosch pivoting algorithm."""
    best_clique: List[int] = []

    def bron_kerbosch(r: Set[int], p: Set[int], x: Set[int]) -> None:
        nonlocal best_clique
        if not p and not x:
            if len(r) > len(best_clique):
                best_clique = list(r)
            return

        pivot = next(iter(p | x))
        for v in list(p - adj[pivot]):
            bron_kerbosch(r | {v}, p & adj[v], x & adj[v])
            p.remove(v)
            x.add(v)

    bron_kerbosch(set(), set(nodes), set())
    return best_clique


def run_4way_prefix_ablation(
    candidates: List[BrandCandidate],
    similarity_matrix: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Run 4-way prefix ablation matrix across Modes A, B, C, and D."""
    n = len(candidates)
    if similarity_matrix is None:
        names = [b.normalized_brand_name for b in candidates]
        similarity_matrix = compute_full_similarity_matrix(names)

    # Pre-index candidates by manufacturer
    mfg_groups: Dict[str, List[int]] = defaultdict(list)
    for idx, b in enumerate(candidates):
        mfg_groups[b.manufacturer].append(idx)

    # Precompute Tier 1 cross-mfg candidate indices (sim >= 0.70)
    rows_70, cols_70 = np.where(
        (similarity_matrix >= 0.70) & (np.triu(np.ones((n, n), dtype=bool), k=1))
    )

    def eval_mode_a() -> Dict[str, Any]:
        """Mode A: No prefix handling (global full-string matching)."""
        tier1, tier2, same_gen, diff_gen = 0, 0, 0, 0
        for r, c in zip(rows_70, cols_70):
            b1, b2 = candidates[r], candidates[c]
            sim = float(similarity_matrix[r, c])
            ph_match = 1 if (b1.phonetic_key and b1.phonetic_key == b2.phonetic_key) else 0
            if sim >= 0.80 or (sim >= 0.70 and ph_match == 1):
                if b1.manufacturer == b2.manufacturer:
                    tier2 += 1
                else:
                    tier1 += 1
                sg, _ = classify_generic_overlap(b1.canonical_generics, b2.canonical_generics)
                if sg == 1:
                    same_gen += 1
                else:
                    diff_gen += 1
        return {
            "mode": "Mode A (No prefix handling)",
            "total_flagged": tier1 + tier2,
            "tier1_count": tier1,
            "tier2_count": tier2,
            "same_generic": same_gen,
            "different_generic": diff_gen,
        }

    def eval_mode_b(thresh: float = 0.80, min_len: int = 4) -> Dict[str, Any]:
        """Mode B: Prefix stripped for same-manufacturer pairs only with min_stem_length."""
        tier1, tier2, same_gen, diff_gen = 0, 0, 0, 0
        # Tier 1 is identical to Mode A cross-mfg
        for r, c in zip(rows_70, cols_70):
            b1, b2 = candidates[r], candidates[c]
            if b1.manufacturer != b2.manufacturer:
                sim = float(similarity_matrix[r, c])
                ph_match = 1 if (b1.phonetic_key and b1.phonetic_key == b2.phonetic_key) else 0
                if sim >= thresh or (sim >= 0.70 and ph_match == 1):
                    tier1 += 1
                    sg, _ = classify_generic_overlap(b1.canonical_generics, b2.canonical_generics)
                    if sg == 1:
                        same_gen += 1
                    else:
                        diff_gen += 1

        # Tier 2: Same-manufacturer with shared prefix stripped
        for _, indices in mfg_groups.items():
            if len(indices) < 2:
                continue
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    b1 = candidates[indices[i]]
                    b2 = candidates[indices[j]]
                    if b1.prefix and b2.prefix and b1.prefix == b2.prefix:
                        s1, s2 = b1.prefix_stem, b2.prefix_stem
                        ph1, ph2 = b1.stem_phonetic_key, b2.stem_phonetic_key
                    else:
                        s1, s2 = b1.normalized_brand_name, b2.normalized_brand_name
                        ph1, ph2 = b1.phonetic_key, b2.phonetic_key

                    if len(s1) < min_len or len(s2) < min_len:
                        continue

                    sim = DamerauLevenshtein.normalized_similarity(s1, s2)
                    ph_match = 1 if (ph1 and ph1 == ph2) else 0
                    if sim >= thresh or (sim >= 0.70 and ph_match == 1):
                        tier2 += 1
                        sg, _ = classify_generic_overlap(
                            b1.canonical_generics, b2.canonical_generics
                        )
                        if sg == 1:
                            same_gen += 1
                        else:
                            diff_gen += 1

        return {
            "mode": f"Mode B (Same-Mfg stripped, min_len={min_len}, thresh={thresh})",
            "total_flagged": tier1 + tier2,
            "tier1_count": tier1,
            "tier2_count": tier2,
            "same_generic": same_gen,
            "different_generic": diff_gen,
        }

    def eval_mode_c(thresh: float = 0.80, min_len: int = 4) -> Dict[str, Any]:
        """Mode C: Prefix stripped globally across all manufacturers."""
        tier1, tier2, same_gen, diff_gen = 0, 0, 0, 0
        stem_names = [b.prefix_stem for b in candidates]
        stem_matrix = compute_full_similarity_matrix(stem_names)

        rows_c, cols_c = np.where(
            (stem_matrix >= 0.70) & (np.triu(np.ones((n, n), dtype=bool), k=1))
        )
        for r, c in zip(rows_c, cols_c):
            b1, b2 = candidates[r], candidates[c]
            s1, s2 = b1.prefix_stem, b2.prefix_stem
            if len(s1) < min_len or len(s2) < min_len:
                continue

            sim = float(stem_matrix[r, c])
            ph_match = 1 if (b1.stem_phonetic_key and b1.stem_phonetic_key == b2.stem_phonetic_key) else 0
            if sim >= thresh or (sim >= 0.70 and ph_match == 1):
                if b1.manufacturer == b2.manufacturer:
                    tier2 += 1
                else:
                    tier1 += 1
                sg, _ = classify_generic_overlap(b1.canonical_generics, b2.canonical_generics)
                if sg == 1:
                    same_gen += 1
                else:
                    diff_gen += 1

        return {
            "mode": "Mode C (Global prefix stripped)",
            "total_flagged": tier1 + tier2,
            "tier1_count": tier1,
            "tier2_count": tier2,
            "same_generic": same_gen,
            "different_generic": diff_gen,
        }

    # Execute Modes A, B, C
    mode_a_res = eval_mode_a()
    mode_b_res = eval_mode_b(0.80, 4)
    mode_c_res = eval_mode_c(0.80, 4)

    # Execute Mode D: Sensitivity grid
    mode_d_grid = []
    for t in [0.75, 0.80, 0.85]:
        for l in [3, 4, 5]:
            grid_res = eval_mode_b(t, l)
            mode_d_grid.append({
                "threshold": t,
                "min_stem_length": l,
                "total_flagged": grid_res["total_flagged"],
                "tier1_count": grid_res["tier1_count"],
                "tier2_count": grid_res["tier2_count"],
                "same_generic": grid_res["same_generic"],
                "different_generic": grid_res["different_generic"],
            })

    return {
        "mode_a": mode_a_res,
        "mode_b": mode_b_res,
        "mode_c": mode_c_res,
        "mode_d_grid": mode_d_grid,
    }


def run_same_mfg_clique_reduction(
    candidates: List[BrandCandidate],
) -> Dict[str, Any]:
    """Compute connected components and maximal cliques among same-manufacturer pairs in Mode A vs Mode B."""
    mfg_map: Dict[str, List[BrandCandidate]] = defaultdict(list)
    for b in candidates:
        mfg_map[b.manufacturer].append(b)

    results = {}
    for mode in ["Mode A", "Mode B"]:
        top_cliques = []
        max_clique_size = 0
        cliques_by_mfg = []

        for mfg, items in mfg_map.items():
            if len(items) < 2:
                continue
            adj = defaultdict(set)
            active_nodes = set()

            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    b1, b2 = items[i], items[j]
                    if mode == "Mode A":
                        s1, s2 = b1.normalized_brand_name, b2.normalized_brand_name
                        p1, p2 = b1.phonetic_key, b2.phonetic_key
                    else:  # Mode B
                        if b1.prefix and b2.prefix and b1.prefix == b2.prefix:
                            s1, s2 = b1.prefix_stem, b2.prefix_stem
                            p1, p2 = b1.stem_phonetic_key, b2.stem_phonetic_key
                        else:
                            s1, s2 = b1.normalized_brand_name, b2.normalized_brand_name
                            p1, p2 = b1.phonetic_key, b2.phonetic_key

                    if len(s1) < 4 or len(s2) < 4:
                        continue

                    sim = DamerauLevenshtein.normalized_similarity(s1, s2)
                    ph_match = 1 if (p1 and p1 == p2) else 0
                    if sim >= 0.80 or (sim >= 0.70 and ph_match == 1):
                        adj[b1.brand_id].add(b2.brand_id)
                        adj[b2.brand_id].add(b1.brand_id)
                        active_nodes.add(b1.brand_id)
                        active_nodes.add(b2.brand_id)

            if active_nodes:
                clique = find_maximal_clique(adj, active_nodes)
                if len(clique) > 1:
                    # Lookup brand names
                    b_dict = {b.brand_id: b.brand_name for b in items}
                    clique_names = [b_dict.get(bid, str(bid)) for bid in clique]
                    cliques_by_mfg.append({
                        "manufacturer": mfg,
                        "clique_size": len(clique),
                        "brands": clique_names,
                    })

        cliques_by_mfg.sort(key=lambda x: x["clique_size"], reverse=True)
        results[mode] = {
            "max_clique_size": cliques_by_mfg[0]["clique_size"] if cliques_by_mfg else 0,
            "top_5_cliques": cliques_by_mfg[:5],
            "total_clique_count": len(cliques_by_mfg),
        }

    return results


def run_ismp_generic_calibration(
    conn: sqlite3.Connection,
    seed: int = SEED,
) -> Dict[str, Any]:
    """Execute ISMP generic pair sanity check against 250 random generic pairs."""
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT canonical_generic FROM generic_components ORDER BY canonical_generic")
    catalog_generics = [r[0] for r in cursor.fetchall() if r[0]]

    # 1. Compute ISMP 25 pairs similarities
    ismp_similarities: List[float] = []
    ismp_phonetic_matches: List[int] = []
    for g1, g2 in ISMP_GENERIC_PAIRS:
        sim = DamerauLevenshtein.normalized_similarity(g1, g2)
        ph1 = pharma_phonetic(g1)
        ph2 = pharma_phonetic(g2)
        pm = 1 if (ph1 and ph1 == ph2) else 0
        ismp_similarities.append(sim)
        ismp_phonetic_matches.append(pm)

    # 2. Sample 250 distinct random non-identical generic pairs with SEED=42
    rng = random.Random(seed)
    random_pairs: List[Tuple[str, str]] = []
    sampled_set: Set[Tuple[str, str]] = set()

    while len(random_pairs) < 250:
        g1, g2 = rng.sample(catalog_generics, 2)
        pair = (min(g1, g2), max(g1, g2))
        if pair not in sampled_set:
            sampled_set.add(pair)
            random_pairs.append(pair)

    random_similarities: List[float] = []
    random_phonetic_matches: List[int] = []
    for g1, g2 in random_pairs:
        sim = DamerauLevenshtein.normalized_similarity(g1, g2)
        ph1 = pharma_phonetic(g1)
        ph2 = pharma_phonetic(g2)
        pm = 1 if (ph1 and ph1 == ph2) else 0
        random_similarities.append(sim)
        random_phonetic_matches.append(pm)

    # 3. Compute stats and Mann-Whitney U / ROC-AUC
    ismp_stats = compute_distribution_stats(ismp_similarities)
    ismp_stats["phonetic_match_rate"] = round(sum(ismp_phonetic_matches) / len(ismp_phonetic_matches), 4)

    rand_stats = compute_distribution_stats(random_similarities)
    rand_stats["phonetic_match_rate"] = round(sum(random_phonetic_matches) / len(random_phonetic_matches), 4)

    u_stat, roc_auc = compute_mann_whitney_u_and_auc(ismp_similarities, random_similarities)

    return {
        "ismp_pair_count": len(ISMP_GENERIC_PAIRS),
        "random_pair_count": len(random_pairs),
        "ismp_stats": ismp_stats,
        "random_stats": rand_stats,
        "mann_whitney_u": u_stat,
        "roc_auc": roc_auc,
        "seed": seed,
    }


def run_runtime_cdist_benchmark(
    candidates: List[BrandCandidate],
) -> Dict[str, Any]:
    """Benchmark full dense SIMD cdist against length-blocked and first-letter blocked cdist."""
    strings = [b.normalized_brand_name for b in candidates]
    n = len(strings)

    # 1. Full Dense SIMD cdist
    tracemalloc.start()
    t0 = time.perf_counter()
    dense_mat = compute_full_similarity_matrix(strings)
    t1 = time.perf_counter()
    current_mem, peak_mem_dense = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rows, cols = np.where((dense_mat >= 0.70) & (np.triu(np.ones((n, n), dtype=bool), k=1)))
    dense_pair_count = len(rows)
    dense_duration = t1 - t0
    dense_mb = (dense_mat.nbytes + peak_mem_dense) / (1024 * 1024)

    # 2. Length-blocked cdist
    tracemalloc.start()
    t2 = time.perf_counter()
    length_pairs = list(compute_blocked_candidates(strings, min_similarity=0.70, block_mode="length"))
    t3 = time.perf_counter()
    _, peak_mem_len = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    length_pair_count = len(length_pairs)
    length_duration = t3 - t2
    length_mb = peak_mem_len / (1024 * 1024)
    length_recall = (length_pair_count / dense_pair_count) * 100.0 if dense_pair_count else 100.0

    # 3. First-letter blocked cdist
    tracemalloc.start()
    t4 = time.perf_counter()
    letter_pairs = list(compute_blocked_candidates(strings, min_similarity=0.70, block_mode="first_letter"))
    t5 = time.perf_counter()
    _, peak_mem_let = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    letter_pair_count = len(letter_pairs)
    letter_duration = t5 - t4
    letter_mb = peak_mem_let / (1024 * 1024)
    letter_recall = (letter_pair_count / dense_pair_count) * 100.0 if dense_pair_count else 0.0

    return {
        "brand_count": n,
        "dense_simd": {
            "execution_seconds": round(dense_duration, 3),
            "peak_memory_mb": round(dense_mb, 2),
            "candidate_pairs_found": dense_pair_count,
            "recall_percent": 100.0,
        },
        "length_blocked": {
            "execution_seconds": round(length_duration, 3),
            "peak_memory_mb": round(length_mb, 2),
            "candidate_pairs_found": length_pair_count,
            "recall_percent": round(length_recall, 2),
        },
        "first_letter_blocked": {
            "execution_seconds": round(letter_duration, 3),
            "peak_memory_mb": round(letter_mb, 2),
            "candidate_pairs_found": letter_pair_count,
            "recall_percent": round(letter_recall, 2),
        },
    }
