---
title: MedAudit BD
emoji: 💊
colorFrom: blue
colorTo: teal
sdk: docker
app_port: 7860
pinned: false
---

# MedAudit-BD

> [!IMPORTANT]
> **Safety and Clinical Framing Disclaimer**:
> MedAudit-BD is an academic research and clinical decision-support **prototype**. It is **not a medical device** and does **not provide clinical advice**. It must not be used for autonomous medical diagnosis, treatment planning, or clinical decision-making. All alternative rankings are labelled strictly as `"same-generic alternative"` (never bioequivalent). All character diff previews are labelled `"visual aid, not validated"`.

A high-performance prescription-audit decision-support engine, 3-band arithmetic residual price validator, and 2-tier Look-Alike Sound-Alike (LASA) detection system engineered for the Bangladeshi pharmaceutical market over `21,714` SKUs and `14,013` deduplicated brands.

---

## 1. Executive Summary & Measured Facts

Every metric in MedAudit-BD is empirically measured and reproducible via scripts pinned to `SEED = 42`:

| Metric Category | Measured Figure | Verification Source Script |
| :--- | :--- | :--- |
| **Catalog Scope** | **21,714** SKUs • **14,013** deduplicated brands • **232** manufacturers | `scripts/00_spike.py` |
| **Generic Parsing** | **99.99%** coverage (21,712/21,714) • 3,770 compounds (`+`) split | `src/medaudit/parsing/generic.py` |
| **Strength Parsing** | **95.27%** overall (20,687/21,714) • **99.14%** non-null strength coverage | `src/medaudit/parsing/strength.py` |
| **Gold Fixture Match** | **99.20%** (248/250 rows) on locked stratified gold fixture (`SHA-256` locked) | `scripts/02_eval_parser.py` |
| **Residual Bands** | **Band 1 (Exact)**: 22,958 (99.40%) • **Band 2 (Drift)**: 116 • **Band 3 (Discrepancy)**: 22 | `docs/PARSER_ERROR_TAXONOMY.md` |
| **SQLite DB Build** | **3.56s** build time • **13.16 MB** DB size • 6 normalized relational tables | `scripts/01_build_db.py` |
| **LASA Precomputed** | **3,358** pairs (2,919 Tier 1 cross-mfg with **90 exact collisions**; 439 Tier 2 same-mfg) | `scripts/03_lasa_ablation.py` |
| **ISMP Calibration** | **0.9918 ROC-AUC** separation vs 250 random generic pairs (`U = 6,199.0`) | `docs/EVALUATION.md` |
| **SIMD cdist Benchmark** | **4.80s** full dense `cdist` • **3.41s** length-blocked `cdist` (**100.0% recall**) | `docs/EVALUATION.md` |
| **Engine Audit Latency** | **15.38ms** (2 items) • **28.09ms** (5 items) • **30.44ms** (8 items) `p50` | `scripts/04_benchmark.py` |
| **HTTP API Latency** | **18.90ms** (2 items) • **31.15ms** (5 items) • **33.67ms** (8 items) `p50` | `scripts/04_benchmark.py` |
| **Memory Footprint** | **67.82 MB** process RSS • Zero external heavy dependencies | `scripts/04_benchmark.py` |
| **Automated Tests** | **171 passing unit & integration tests** in **1.20s** (`pytest`) | `tests/` |

---

## 2. Core Modules

```
                    MedAudit-BD Architectural Pipeline
                    
 [ Raw Medicine Catalog ] (Mahadih534/all-Bangladeshi-medicines, 21,714 SKUs, 10 columns)
           │
           ▼
 [ Schema Validation & Ingestion ] ──> Maps upstream 'brand id' to SKU product_id
           │
 ┌─────────┴──────────────────────────────┐
 │ Deterministic Multi-Strategy Parsers   │
 │  ├── generic.py   (Compound '+', INN/BP synonym mapping, chemical salts)
 │  ├── strength.py  (Mass/volume conversion, liquid denominator, % w/v, puffs)
 │  └── price.py     (Container parsing, pack arithmetic & 3-band residual classifier)
 └─────────┬──────────────────────────────┘
           ▼
 [ SQLite Relational Store: medaudit.db (13.16 MB) ]
   ├── brands (14,013 rows)           ├── generic_components (26,433 rows)
   ├── products (21,714 rows)         ├── strength_components (25,138 rows)
   ├── price_packs (23,096 rows)      ├── lasa_pairs (3,358 rows)
   └── parse_anomalies (1,087 rows)
           │
 ┌─────────┴──────────────────────────────┐
 │ Prescription Auditor & LASA Warning    │
 │  ├── duplicates.py   (Single, compound, single-vs-compound active ingredient overlap)
 │  ├── release_type.py (Intra-regimen IR vs XR kinetics & 10x catalog shelf look-alikes)
 │  ├── nti.py          (Narrow Therapeutic Index brand substitution locking)
 │  ├── alternatives.py (Same-generic alternative ranking by normalized BDT unit price)
 │  └── tiers.py        (2-tier LASA warnings, house prefix stripping & visual diff previews)
 └─────────┬──────────────────────────────┘
           ▼
 [ FastAPI Service & Single-Page UI ] ──> /v1/health, /v1/brands/search, /v1/prescription/audit, /
```

### Module A: Multi-Strategy Price Parser & Arithmetic Residual Classifier
- **The Problem**: 38.33% of Bangladeshi packaging container strings break simple regex patterns (`"3 x 10's Pack: ৳ 210.00 (Unit Price: ৳ 7.00)"`, `"100 ml Bottle: ৳ 85.00"`, `"Vial: ৳ 450.00"`, `"1 Kit: ৳ 1,250.00"`).
- **The Solution**: Multi-strategy tokenizer that computes arithmetic residual:
  $$\text{Residual } \Delta = |\text{pack\_price\_bdt} - (\text{unit\_price\_bdt} \times \text{pack\_qty})|$$
  - **Band 1 (Exact Match, $\Delta \le 0.01$ BDT)**: 22,958 rows (**99.40%**).
  - **Band 2 (Rounding Drift, $\Delta \le 0.05 \times \text{pack\_price}$ or $\le 0.50$ BDT)**: 116 rows (**0.50%**).
  - **Band 3 (Hard Discrepancy, logged to `parse_anomalies`)**: 22 rows (**0.10%**).

### Module B: Prescription Auditor Engine
Audits 2 to 8 prescribed items in a single pass:
1. **Unambiguous Item Resolution**: Resolves catalog SKUs or returns candidate presentations (`AMBIGUOUS`) without guessing.
2. **Duplicate Active Ingredients**: Detects single-ingredient collisions, compound collisions, and single-vs-compound overlaps (e.g. `Napa` [Paracetamol] + `Ace Plus` [Paracetamol + Caffeine]).
3. **Release Kinetics & 10x Strength Hazards**: Identifies immediate-release vs extended-release conflicts (`IR` vs `XR/SR/CR/EC`) and flags catalog same-brand 10x packaging look-alikes (e.g. `Algin 50mg` vs `Algin 5mg/2ml`).
4. **Narrow Therapeutic Index (NTI) Locking**: Locks substitution on Warfarin, Levothyroxine, Theophylline, Digoxin, Carbamazepine, Lithium, and Insulins.
5. **Same-Generic Alternative Ranking**: Ranks alternative brands by unit price, displaying savings percentages, container types, and residual bands.

### Module C: 2-Tier LASA Warning Engine & Prefix Stemming
- **Tier 1 (Cross-Manufacturer)**: Compares full brand names across different manufacturers using Damerau-Levenshtein normalized similarity (satisfies metric triangle inequality) combined with deterministic pharmaceutical phonetic canonicalization. Flags pairs with $\text{sim} \ge 0.80$ or ($\text{sim} \ge 0.70$ + phonetic match). Identifies and monitors **90 exact brand collision pairs** across manufacturers.
- **Tier 2 (Same-Manufacturer)**: Strips shared manufacturer house prefixes (e.g. `G-*`, `A-*`, `SB-*`, `Kvit-*`, `Neo-*`) and compares post-prefix stems with `min_stem_length = 4`. Prevents artificial prefix clique clustering (cutting Mode A Tier 2 alerts from 596 to 439).
- **Safety Framing**: Pairs sharing generic components are labelled `"same-generic pair (lower priority)"` (never "safe" or "bioequivalent"). Diff previews (`diff_preview`) are marked `"visual aid, not validated"`.

---

## 3. One-Click Recruiter Demo Prescriptions

Launch the interactive single-page UI at `http://127.0.0.1:8000/` and click any demo button to evaluate the complete pipeline instantly:

| Demo Button | Prescribed Items Loaded | What It Demonstrates |
| :--- | :--- | :--- |
| **Demo 1: Hidden Compound Overlap & Cheaper Brands** | `Napa` (500mg) + `Ace Plus` (500mg+65mg) + `Seclo` (20mg) | Detects hidden Paracetamol overlap between single and compound pills; ranks cheaper same-generic Omeprazole alternatives with unit prices. |
| **Demo 2: NTI Lock, Release & 10x Shelf Hazard** | `Warin` (5mg Warfarin) + `Napa Extend` (665mg XR) + `Algin` (50mg) | Flags NTI active ingredient (`substitution_locked = true`); warns on XR kinetics mismatch; flags 10x shelf look-alike sibling (`Algin 5mg/2ml`). |
| **Demo 3: Tier 1 & Tier 2 LASA Collision Showcase** | `A-Mycin` (Aristopharma) + `B-Mycin` (Gaco) | Detects cross-manufacturer LASA collision (86% lexical similarity) with character diff preview string `[A]-Mycin vs [B]-Mycin (visual aid, not validated)`. |

---

## 4. API Endpoints

The FastAPI REST service is fully documented via interactive Swagger UI at `/docs`:

### `GET /v1/health`
Returns system status, SQLite connection health, and exact row counts:
```json
{
  "status": "ok",
  "database_connected": true,
  "table_counts": {
    "brands": 14013,
    "products": 21714,
    "price_packs": 23096,
    "lasa_pairs": 3358,
    "parse_anomalies": 1087
  }
}
```

### `GET /v1/brands/search?q={query}&limit={limit}`
Performs SQL prefix and RapidFuzz fuzzy search returning ranked candidate SKUs:
```json
[
  {
    "product_id": 10452,
    "brand_id": 7764,
    "brand_name": "Napa",
    "dosage_form": "Tablet",
    "strength": "500 mg",
    "manufacturer": "Beximco Pharmaceuticals Ltd.",
    "similarity_score": 100.0
  }
]
```

### `POST /v1/prescription/audit`
Accepts 2 to 8 prescribed items (enforces HTTP 422 if `<2` or `>8` items):
```json
// Request
{
  "items": [
    { "product_id": 10452 },
    { "product_id": 10557 }
  ],
  "manufacturer_filter": "Square Pharmaceuticals Ltd."
}
```
Returns overall status (`OK`, `FLAG`, `UNVERIFIED`, `AMBIGUOUS`), per-check outcomes, and mandatory statutory disclaimer.

### `GET /v1/brands/{brand_id}/lasa`
Returns precomputed Tier 1 and Tier 2 LASA pairs ordered by `same_generic ASC, edit_similarity DESC`.

---

## 5. Quickstart & Installation

### Local Virtual Environment
```bash
# 1. Clone repository
git clone https://github.com/TahmidShafi/MedAudit-BD.git
cd MedAudit-BD

# 2. Create and activate virtual environment (Python 3.11+)
python -m venv .venv
.venv\Scripts\activate       # On Windows
# source .venv/bin/activate  # On Linux/macOS

# 3. Install dependencies in editable mode
pip install -e ".[dev]"

# 4. Run full test suite (171 tests)
pytest -v

# 5. Launch web application and API
uvicorn medaudit.api.main:app --host 127.0.0.1 --port 8000
```
Open **`http://127.0.0.1:8000/`** for the interactive single-page UI, or **`http://127.0.0.1:8000/docs`** for OpenAPI specs.

### Docker Deployment
```bash
# Build Docker image
docker build -t medaudit-bd .

# Run container
docker run -p 8000:8000 medaudit-bd
```

---

## 6. How to Reproduce All Research Artifacts

Every figure and table is generated by a standalone script in `scripts/`:

```bash
# Phase 0: Feasibility Spike, 10-column schema & 300-row container distribution
python scripts/00_spike.py

# Phase 1: Coverage & presentation duplicate breakdown
python scripts/01_phase1_coverage.py

# Phase 2B: 250-row gold fixture evaluation & 3-band residual classifier
python scripts/02_eval_parser.py

# Phase 3: SQLite database build (produces data/processed/medaudit.db)
python scripts/01_build_db.py

# Phase 4: 4-way prefix ablation matrix, clique reduction, ISMP calibration & cdist benchmark
python scripts/03_lasa_ablation.py

# Phase 5: 500-iteration in-process engine vs HTTP TestClient latency benchmark
python scripts/04_benchmark.py
```

---

## 7. Project Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): Complete technical design, data flow diagrams, relational schema, residual classifier logic, and LASA stem-stripping algorithms.
- [`docs/EVALUATION.md`](docs/EVALUATION.md): Full empirical evaluation report containing the 4-way prefix ablation matrix, clique reduction tables, ISMP 0.9918 ROC-AUC calibration, and 500-iteration latency percentiles (`p50`, `p95`, `p99`).
- [`docs/PARSER_ERROR_TAXONOMY.md`](docs/PARSER_ERROR_TAXONOMY.md): Packaging container error taxonomy, 3-band residual classifier distributions, and fixture validation analysis.
- [`docs/SPIKE_REPORT.md`](docs/SPIKE_REPORT.md): Phase 0 findings, real 10-column schema discovery, and stratified container sampling distributions.
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md): Clinical decision-support boundaries, lack of market-share denominator, absence of physical packaging trade-dress, and upstream data anomalies.
- [`docs/DATA_LICENSE.md`](docs/DATA_LICENSE.md): Legal provenance and data redistribution guidelines.
