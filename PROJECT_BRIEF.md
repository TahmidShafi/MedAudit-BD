# PROJECT BRIEF: MedAudit-BD

You are a senior backend/data engineer acting as my pair-programmer. We are building a portfolio project solo, part-time, over ~6-7 weeks. Work in PHASES. After each phase, STOP, summarize what you did, show test results, and wait for my "go" before starting the next phase. Never skip ahead.

## 0. GROUND RULES (apply to every phase)
1. Honesty over polish. Never invent dataset facts, row counts, accuracy numbers, benchmark results, or library behaviour. If a number is unknown, run code to measure it or write "NOT YET MEASURED". Every figure in the README must come from a script in the repo.
2. Safety framing. This is a decision-support PROTOTYPE, not a medical device and not clinical advice. The README, API responses, and UI footer must say so.
3. Do not scrape any website. Use only the dataset files I provide or download from Hugging Face via the `datasets` library or `huggingface_hub`.
4. Check the dataset licence on its Hugging Face page and record it in `docs/DATA_LICENSE.md` before we publish any derived data. If the licence is unclear, say so and do not publish derived datasets.
5. Test-driven: write tests for each module before or alongside the code. Use `pytest`. All tests must pass before a phase is "done".
6. Keep code simple and typed (Python 3.11+, type hints, pydantic v2 models). Use a local `.venv` (`python -m venv .venv` and `pip install -e ".[dev]"` via `pyproject.toml`). Pin `SEED = 42` in `src/medaudit/config.py` for all sampling scripts. Allowed core libraries: `datasets`, `huggingface_hub`, `pydantic`, `fastapi`, `uvicorn`, `rapidfuzz`, `pytest`, `httpx`. Do not add heavy frameworks.
7. Every phase ends with: (a) files changed, (b) tests run and results, (c) measured numbers, (d) known limitations, (e) a proposed next step. No vague claims like "works well".
8. If something in this brief conflicts with what the data actually looks like, tell me and propose a change. Do not silently work around it.

## 1. WHAT WE ARE BUILDING
A Bangladeshi prescription-audit engine built on the open dataset `Mahadih534/all-Bangladeshi-medicines` (Hugging Face; reported columns: brand name, type, slug, dosage form, generic, strength, manufacturer, package container). Verify the real schema in Phase 0 and use whatever it actually contains.

Three modules, in priority order:
- Module A (core): Package-container price PARSER (`price.py`), strength parser (`strength.py`), and compound generic parser (`generic.py`).
- Module B (core): Prescription AUDITOR (`duplicates.py`, `release_type.py`, `nti.py`, `alternatives.py`). Use the term "same-generic alternative", never "bioequivalent".
- Module C (secondary): Tiered LASA brand-name WARNINGS, precomputed offline over deduplicated brand names (`brands` table).
  - Tier 1: different manufacturers, compare full brand string.
  - Tier 2: same manufacturer, compare the post-prefix stem (strip shared manufacturer prefix token). Enforce a configurable minimum stem length (default 4 chars). Skip Tier 2 below it.
  - Use normalized Damerau-Levenshtein (`rapidfuzz.process.cdist`) plus a deterministic pharma phonetic key. Do NOT use a BK-tree with Jaro-Winkler or OSA.
  - Do NOT claim Tall-Man lettering effectiveness. Optional: pairwise diff highlighting labelled "visual aid, not validated".
  - Label output "lexical similarity warning, not clinically validated". Flag same-generic pairs as "same-generic pair" (lower priority), not as safe.

Explicitly OUT of scope: DDI checking, dosing advice, diagnosis, LLM-generated clinical text, multi-pack knapsack/ILP optimisation, npm widgets, pharmacist annotation studies, scraping.

## 2. ARCHITECTURE & SQLITE SCHEMA
Storage: SQLite (stdlib). Explicitly separate SKU-level rows (`products`) from deduplicated brand names (`brands`):
- `brands`: deduplicated `(brand_id, brand_name, normalized_brand_name, manufacturer, prefix_stem)`
- `products`: 1 row per raw HF dataset SKU row `(product_id, brand_id, raw_brand_name, type, slug, dosage_form, raw_generic, raw_strength, normalized_strength, release_type, manufacturer, raw_package_container)`
- `price_packs`: 1-to-many from `products` `(pack_id, product_id, container_type, volume_ml, pack_qty, unit_price_bdt, pack_price_bdt, normalized_unit_price_bdt, comparison_unit, residual_band, residual_delta, source_span)`
- `generic_components`: 1-to-many from `products` `(product_id, component_order, canonical_generic, raw_component, salt, is_nti)`
- `lasa_pairs`: keyed on `brands` `(brand_id_a, brand_id_b, tier, edit_similarity, phonetic_match, same_generic, same_manufacturer, diff_preview)`
- `parse_anomalies`: `(anomaly_id, product_id, module, reason_code, raw_string, details)`

API (FastAPI, versioned):
- GET  /v1/health
- GET  /v1/brands/search?q=
- POST /v1/prescription/audit
- GET  /v1/brands/{brand_id}/lasa
Every audit response includes a `disclaimer` field and a per-check `status` (`OK` / `FLAG` / `UNVERIFIED`).