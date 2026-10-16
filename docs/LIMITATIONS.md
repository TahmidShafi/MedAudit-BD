# MedAudit-BD: Engineering & Clinical Limitations

MedAudit-BD is a research prototype designed to demonstrate deterministic rule-based prescription auditing, lexical look-alike sound-alike (LASA) analysis, and packaging arithmetic validation. It operates under several explicit technical and domain constraints.

---

## 1. Decision-Support Prototype Only (No Clinical Validation)

MedAudit-BD is **not a medical device** and does **not provide clinical advice**. 
- The system evaluates lexical similarities, string tokens, and database associations. It does not possess a pharmacokinetic or clinical efficacy model.
- Same-generic alternative rankings are ordered strictly by normalized unit price in Bangladeshi Taka (BDT). They are explicitly labelled `"same-generic alternative"` and **must never be construed as bioequivalent**. In Bangladesh, bioequivalence studies are only available for a fraction of registered products; pharmaceutical equivalence in active ingredient and strength does not guarantee identical in-vivo bioavailability.
- Character difference highlights (`diff_preview`) are provided strictly as visual aids (`"visual aid, not validated"`) and have not been validated in a prospective clinical human-factors trial.

---

## 2. Lack of Prescribing Frequency & Market Share Denominators

- The LASA ranking and alert system operates unweighted across all **14,013 deduplicated brand names** present in the catalog.
- In clinical practice, LASA hazards are governed heavily by market share and dispensing velocity: a similarity between two top-10 high-volume drugs poses orders of magnitude more real-world hazard than a collision between two obscure, rarely prescribed specialist formulations.
- Because public dispensing frequency data and sales volume denominators are unavailable in the open dataset, all pairs meeting the lexical threshold are flagged equally.

---

## 3. Absence of Physical Packaging Trade-Dress & Handwriting Data

- Real-world dispensing errors in Bangladeshi retail pharmacies frequently stem from:
  1. Identical blister pack foil designs, strip color schemes, or box trade-dress among same-manufacturer brands.
  2. Illegible cursive handwriting on paper prescription slips.
- MedAudit-BD evaluates only digital text tokens. It has no access to computer-vision models of carton color palettes, packaging fonts, or handwritten doctor notes.

---

## 4. Upstream Scraped Dataset Data Quality Anomaly Burden

The upstream Hugging Face dataset (`Mahadih534/all-Bangladeshi-medicines`) was scraped from public web portals and exhibits concrete upstream data defects identified during Phase 0 and Phase 2B:
- **79 Duplicate Brand-Manufacturer Combinations**: 70 brand names exist in duplicate rows under different manufacturer entities (e.g. generic names mistakenly entered as brand names).
- **17 Unparseable Packaging Containers**: SKUs where packaging text contains nonsensical strings (e.g. `"2 x 10's Pack"` with null price, or malformed characters).
- **2 Missing Generics**: SKUs where the generic active ingredient was omitted entirely in the source database.
- **Thousand-Separator Upstream Transcription Flaws**: In certain cases (e.g., SKUs `17285` and `28654`), commas in unit prices were misplaced upstream (e.g. `1,70` instead of `170`), creating Band 3 residual discrepancies.

---

## 5. Potential False Negatives on Complex Herbal & Non-Standard Generics

- While single-ingredient and standard chemical compound generics (e.g., `paracetamol + caffeine`, `amoxicillin + clavulanic acid`) achieve 99.99% parsing coverage, complex multi-herb Ayurvedic/Unani preparations and proprietary multi-vitamin mixtures (e.g., `Pregcare`, `Affrox`, `Cholera Fluid`) cannot be decomposed into standard chemical canonical generics.
- For these formulations, the auditor sets generic resolution status to `UNVERIFIED`. The system will not flag duplicate active ingredients for unverified formulations, presenting a theoretical risk of false-negative duplicate detection for multi-herb compounds.
