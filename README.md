# MedAudit-BD

> **Disclaimer**: MedAudit-BD is an academic research and decision-support **prototype**. It is **not a medical device** and does **not provide clinical advice**. It must not be used for medical diagnosis, treatment planning, or clinical decision-making.

A high-integrity prescription-audit engine and lexical safety tool for the Bangladeshi pharmaceutical market, built on top of the open dataset `Mahadih534/all-Bangladeshi-medicines` (21,714 SKUs).

---

## 1. Project Overview

MedAudit-BD provides automated auditing for Bangladeshi medical prescriptions to detect:
1. **Packaging & Unit Price Extraction**: Multi-strategy container price parsing across standard strips, bulk packs, liquid volumes, injectables, inhalers, and drops.
2. **Generic & Strength Normalization**: Compound active ingredient splitting, chemical salt/ester radical separation, BP-to-INN synonym mapping, and mass/volume normalization.
3. **Prescription Integrity Audit**: Duplicate active ingredient detection, release mechanism compatibility, narrow therapeutic index (NTI) monitoring, and same-generic cost alternatives.
4. **Tiered LASA (Look-Alike / Sound-Alike) Detection**: Offline precomputed lexical and phonetic brand-name similarity warnings across 14,013 deduplicated brand entities.

---

## 2. Empirical Dataset Facts (Measured via Scripts)

All figures below are measured directly from the source dataset via `scripts/00_spike.py` and `scripts/01_phase1_coverage.py` using `SEED = 42`:

- **Total Physical SKUs**: 21,714
- **Deduplicated Brand Entities**: 14,013 `(brand_name, manufacturer)` combinations (13,934 unique brand names across 232 licensed manufacturers)
- **Active Generic Formulations**: 1,661 distinct generic formulas
  - **Compound Generics (`+`)**: 3,770 SKUs (17.36%) across 382 distinct compound formulas
  - **Salts / Radicals**: 8,414 SKUs (38.75%) contain chemical salt forms
- **Medicine Classification**:
  - `allopathic`: 21,363 SKUs (98.38%)
  - `herbal`: 351 SKUs (1.62%)
- **Packaging Format Complexity** (from 300-row stratified spike sample):
  - Standard unit + single pack: **60.33%**
  - Liquid / topical / injectable volume containers: **29.33%**
  - Multi-tier / multi-pack pricing structures: **6.33%**
  - Specialized formats (metered sprays, contraceptive blisters): **2.00%**
  - Unit price only without pack quantity: **1.33%**
  - Price unavailable / missing: **0.67%**
  - **Single simple regex failure rate**: **38.33%** (necessitating a multi-strategy parsing pipeline)

---

## 3. Implementation Status

| Phase | Description | Status | Test Coverage |
| :--- | :--- | :---: | :---: |
| **Phase 0** | Feasibility Spike & Hugging Face Licence Audit | **Completed** | Verbatim findings in [`docs/SPIKE_REPORT.md`](docs/SPIKE_REPORT.md) & [`docs/DATA_LICENSE.md`](docs/DATA_LICENSE.md) |
| **Phase 1** | Schema Ingest, Compound Generic & Strength Parsers | **Completed** | 68 unit tests passing (99.99% generic, 95.27% strength coverage) |
| **Phase 2A** | 250-Row Stratified Ground-Truth Price Fixture | **Completed** | 5 validation tests passing ([`tests/fixtures/price_labels.csv`](tests/fixtures/price_labels.csv)) |
| **Phase 2B** | Package Container Multi-Strategy Price Parser (`price.py`) | *Next* | Target: ≥96% accuracy on 250-row gold fixture |
| **Phase 2C** | SQLite Database Ingestion & Relational Schema | *Upcoming* | 5 relational tables (`brands`, `products`, `price_packs`, etc.) |
| **Phase 3** | Prescription Auditor Engine (`duplicates`, `release_type`, `nti`, `alternatives`) | *Upcoming* | Multi-check decision-support auditor |
| **Phase 4** | Offline Tiered LASA Pair Generator | *Upcoming* | Normalized Damerau-Levenshtein + phonetic keys |
| **Phase 5** | Versioned FastAPI REST Service & Minimal UI | *Upcoming* | `GET /v1/health`, `POST /v1/prescription/audit`, etc. |

---

## 4. Setup & Testing

### Installation

Requires Python 3.11+:

```bash
# Clone the repository
git clone https://github.com/TahmidShafi/MedAudit-BD.git
cd MedAudit-BD

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies in editable mode
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest -v
```

All 73 unit tests should pass in under 1 second.

---

## 5. Data Provenance & Licensing

- **Dataset**: `Mahadih534/all-Bangladeshi-medicines` by Mahadi Hassan, hosted on Hugging Face Datasets (tagged `CC-BY-2.0`).
- **Policy**: In accordance with project ground rules, raw dataset dumps and derived SQLite databases are **strictly excluded from public distribution** (`.gitignore`).
- For complete legal review and provenance gap analysis, see [`docs/DATA_LICENSE.md`](docs/DATA_LICENSE.md).
