# MedAudit-BD: Architecture & Technical Design

## 1. System Overview & Data Flow

MedAudit-BD is a high-performance, deterministic prescription audit and look-alike sound-alike (LASA) decision-support engine engineered specifically for the Bangladeshi pharmaceutical market.

```mermaid
flowchart TD
    RawCSV["data/raw/medicine.csv<br/>(21,714 SKU rows, 10 columns)"] --> Ingest["src/medaudit/ingest/loader.py<br/>(10-Column Schema Validation)"]
    
    subgraph Parsers ["Deterministic Parsers"]
        Ingest --> GenParse["generic.py<br/>(Compound Splitting, Salts)"]
        Ingest --> StrParse["strength.py<br/>(Unit Normalization to mg/ml)"]
        Ingest --> PriceParse["price.py<br/>(Container & 3-Band Residuals)"]
    end
    
    subgraph SQLiteDB ["data/processed/medaudit.db (13.16 MB)"]
        GenParse --> GC["generic_components<br/>(26,433 rows)"]
        StrParse --> SC["strength_components<br/>(25,138 rows)"]
        PriceParse --> PP["price_packs<br/>(23,096 rows)"]
        PriceParse --> PA["parse_anomalies<br/>(1,087 rows)"]
        Ingest --> BR["brands<br/>(14,013 deduplicated rows)"]
        Ingest --> PR["products<br/>(21,714 SKU rows)"]
    end
    
    subgraph LASA ["Offline LASA Precomputation Engine"]
        BR --> LASACand["candidates.py<br/>(Prefix Extraction & Generics Mapping)"]
        LASACand --> LASAPhon["phonetic.py<br/>(Deterministic Pharma Phonetic Canonicalizer)"]
        LASAPhon --> LASATiers["tiers.py<br/>(2-Tier Damerau-Levenshtein SIMD cdist)"]
        LASATiers --> LP["lasa_pairs<br/>(3,358 precomputed rows)"]
    end
    
    subgraph AuditEngine ["Prescription Auditor (engine.py)"]
        PR --> Res["search.py (Item Resolution)"]
        GC --> Dup["duplicates.py (Compound Overlaps)"]
        SC --> Rel["release_type.py (XR vs IR & 10x Hazards)"]
        GC --> NTI["nti.py (NTI Substitution Locks)"]
        PP --> Alt["alternatives.py (Same-Generic Ranking)"]
        LP --> LASAWarn["tiers.py (LASA Warnings)"]
    end
    
    subgraph Presentation ["Presentation & Serving"]
        AuditEngine --> API["FastAPI Service (api/main.py)<br/>/v1/health, /v1/brands/search, /v1/prescription/audit, /v1/brands/{id}/lasa"]
        API --> UI["Single-Page Application (web/index.html)<br/>Live Autocomplete, Demo Prescriptions, Badges"]
    end
```

---

## 2. SQLite Database Schema (6 Tables + Anomalies)

The persistence layer separates SKU-level product variations from deduplicated brand entities, indexing foreign keys and text search vectors for sub-millisecond execution.

### Relational Schema Diagram
```mermaid
erDiagram
    BRANDS ||--o{ PRODUCTS : "contains SKUs"
    BRANDS ||--o{ LASA_PAIRS : "brand_a"
    BRANDS ||--o{ LASA_PAIRS : "brand_b"
    PRODUCTS ||--o{ GENERIC_COMPONENTS : "has active ingredients"
    PRODUCTS ||--o{ STRENGTH_COMPONENTS : "has strengths"
    PRODUCTS ||--o{ PRICE_PACKS : "has packaging options"
    PRODUCTS ||--o{ PARSE_ANOMALIES : "logs anomalies"

    BRANDS {
        int brand_id PK
        string brand_name
        string normalized_brand_name
        string manufacturer
        string prefix_stem
    }
    PRODUCTS {
        int product_id PK
        int brand_id FK
        string raw_brand_name
        string type
        string slug
        string dosage_form
        string raw_generic
        string raw_strength
        string normalized_strength
        string release_type
        string manufacturer
        string raw_package_container
        string raw_package_size
        string parse_status
    }
    GENERIC_COMPONENTS {
        int component_id PK
        int product_id FK
        int component_order
        string canonical_generic
        string raw_component
        string salt
        string annotation
        int is_nti
    }
    STRENGTH_COMPONENTS {
        int strength_id PK
        int product_id FK
        int component_order
        real numeric_value
        string canonical_unit
        real per_volume_value
        string per_volume_unit
        string raw_component_strength
    }
    PRICE_PACKS {
        int pack_id PK
        int product_id FK
        string container_type
        real volume_or_weight_value
        string volume_or_weight_unit
        int pack_qty
        real unit_price_bdt
        real pack_price_bdt
        real normalized_unit_price_bdt
        string comparison_unit
        string residual_band
        real residual_delta
        string source_span
    }
    PARSE_ANOMALIES {
        int anomaly_id PK
        int product_id FK
        string module
        string reason_code
        string raw_string
        string details
    }
    LASA_PAIRS {
        int brand_id_a PK,FK
        int brand_id_b PK,FK
        int tier
        real edit_similarity
        int phonetic_match
        int same_generic
        int same_manufacturer
        string diff_preview
    }
```

---

## 3. Package Container & Arithmetic Residual Classifier Design

The package container string parser (`price.py`) extracts discrete packaging container models and validates unit price against total pack price using arithmetic residuals:

$$\text{Residual } \Delta = |\text{pack\_price\_bdt} - (\text{unit\_price\_bdt} \times \text{pack\_qty})|$$

```
+---------------------------------------------------------------------------------+
| Raw Container String: "3 x 10's Pack: ৳ 210.00 (Unit Price: ৳ 7.00)"            |
+---------------------------------------------------------------------------------+
                                       |
                                       v
                     [ Tokenizer & Multi-Pack Multiplier ]
                      Container: Blister Pack | Qty: 30
                                       |
                                       v
         [ Arithmetic Residual: |210.00 - (7.00 * 30)| = |210.00 - 210.00| = 0.00 ]
                                       |
          +----------------------------+----------------------------+
          |                                                         |
          v                                                         v
   Delta <= 0.01 BDT                                         Delta > 0.01 BDT
+-----------------------+                                           |
|     BAND 1: EXACT     |                                           v
|  (22,958 rows, 99.4%) |                           +-------------------------------+
+-----------------------+                           | Delta <= 0.05 * Pack Price OR |
                                                    | Drift <= 0.50 BDT             |
                                                    +-------------------------------+
                                                              |           |
                                                            Yes           No
                                                              |           |
                                                              v           v
                                                    +-------------+ +--------------------+
                                                    |   BAND 2:   | |      BAND 3:       |
                                                    |  ROUNDING   | |  HARD DISCREPANCY  |
                                                    |    DRIFT    | | (Logged to         |
                                                    |  (116 rows) | |  parse_anomalies)  |
                                                    |             | | (22 rows)          |
                                                    +-------------+ +--------------------+
```

---

## 4. 2-Tier LASA Brand-Name Warning Architecture

Look-Alike Sound-Alike (LASA) brand confusion represents a primary medication hazard in Bangladesh. The 2-Tier LASA pipeline evaluates 14,013 deduplicated brand names using normalized Damerau-Levenshtein distance (which satisfies the metric space triangle inequality) combined with pharmaceutical phonetic matching:

```mermaid
flowchart TD
    Pair["Brand Pair (A, B)"] --> MfgCheck{"Manufacturer A == Manufacturer B?"}
    
    MfgCheck -- "No (Different Mfg)" --> T1["Tier 1 Evaluation<br/>Compare Full Normalized Brand Names"]
    T1 --> T1Rule{"Similarity >= 0.80 OR<br/>(Similarity >= 0.70 AND Phonetic Match)?"}
    T1Rule -- "Yes" --> T1Flag["Tier 1 Warning Flagged<br/>Check Same-Generic Overlap"]
    T1Rule -- "No" --> Clear["No Warning"]
    
    MfgCheck -- "Yes (Same Mfg)" --> StemCheck{"Shared House Prefix Token?<br/>(e.g. G-*, A-*, Kvit-*, Neo-*)"}
    StemCheck -- "Yes" --> Strip["Strip Prefix Token<br/>Extract Post-Prefix Stem"]
    StemCheck -- "No" --> FullStem["Retain Full Brand Name"]
    
    Strip --> LenCheck{"Min Stem Length >= 4 Chars?"}
    FullStem --> LenCheck
    
    LenCheck -- "No (< 4 chars)" --> SkipStem["Skip Comparison<br/>(Prevents Short-Stem Explosion)"]
    LenCheck -- "Yes (>= 4 chars)" --> T2Rule{"Stem Sim >= 0.80 OR<br/>(Stem Sim >= 0.70 AND Phonetic Match)?"}
    
    T2Rule -- "Yes" --> T2Flag["Tier 2 Warning Flagged<br/>Check Same-Generic Overlap"]
    T2Rule -- "No" --> Clear
    
    T1Flag --> Overlap{"Same Canonical Generic Set?"}
    T2Flag --> Overlap
    
    Overlap -- "Yes" --> LabelLow["Label: 'same-generic pair (lower priority)'<br/>Never label as safe or bioequivalent"]
    Overlap -- "No" --> LabelDiff["Label: 'different-generic lexical warning'<br/>High Clinical Risk"]
```

### Deterministic Phonetic Canonicalizer (`phonetic.py`)
Zero-dependency canonicalizer operating without Soundex 4-character truncation:
1. Strips non-alphabetic characters and lowercases.
2. Normalizes pharma digraphs: `ph -> f`, `ch -> k`, `rh -> r`, `th -> t`, `c([eiy]) -> s`, `c -> k`, `q -> k`, `x -> z`, `y -> i`.
3. Strips silent `h` after consonants (`gh`, `dh`, `bh`, `kh`).
4. Collapses consecutive duplicate letters.
5. Strips all vowels (`a, e, i, o, u`) except the very first character of the string.
6. Re-collapses consecutive duplicate letters.
