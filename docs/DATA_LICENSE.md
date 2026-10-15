# Data Licensing & Provenance Review: Mahadih534/all-Bangladeshi-medicines

## 1. Hugging Face Dataset Metadata

- **Repository**: [`Mahadih534/all-Bangladeshi-medicines`](https://huggingface.co/datasets/Mahadih534/all-Bangladeshi-medicines)
- **Author**: Mahadi Hassan ([Mahadih534](https://huggingface.co/Mahadih534))
- **Date Created**: 2024-08-31T09:48:26.000Z
- **Last Modified**: 2024-08-31T09:52:11.000Z
- **Primary Data File**: `medicine.csv` (~1.14 MB uncompressed)
- **Dataset Card Content**: Minimal. The repository README consists exclusively of the following YAML frontmatter:
  ```yaml
  ---
  license: cc-by-2.0
  ---
  ```
- **Hugging Face API Tags**: `license:cc-by-2.0`, `size_categories:10K<n<100K`, `format:csv`, `modality:text`, `library:datasets`
- **Machine-Readable Croissant / Schema.org License**: `https://choosealicense.com/licenses/cc-by-2.0/` (Creative Commons Attribution 2.0 Generic)

---

## 2. Provenance & Intellectual Property Assessment

1. **Declared Licence**: The uploader explicitly tagged the repository as **`CC-BY-2.0` (Creative Commons Attribution 2.0 Generic)**.
2. **Provenance Gap**: The dataset card provides **no documentation** regarding data origin, collection methodology, curation date, or upstream rights. The records (brand names, dosage forms, generic compositions, strengths, manufacturers, and indicative package prices in Bangladeshi Taka) strongly indicate secondary compilation or extraction from public Bangladeshi pharmaceutical indexes (such as Medex, DIMS, or DGDA gazettes).
3. **Database & Upstream Rights**: Because upstream database compilation rights in Bangladesh cannot be formally verified from the uploader's metadata, the declared CC-BY-2.0 licence applies only to the uploader's contribution and cannot indemnify downstream redistributors against third-party database rights.

---

## 3. Compliance & Distribution Policy (Ground Rules 4 & 9)

In compliance with `PROJECT_BRIEF.md` Ground Rules 2, 4, and 9:

- **DO NOT PUBLISH DERIVED DATASETS**: Neither the raw `medicine.csv` nor enriched derived database dumps (e.g. SQLite databases, parquet files, or extracted pricing tables) shall be committed to public repositories or republished.
- **Local Research Prototype**: The dataset is downloaded and cached strictly in local ignored storage (`data/raw/`) for decision-support algorithm development, benchmarking, and unit testing.
- **Attribution**: Where results or figures are cited in portfolio documentation, attribute the source dataset:
  > *Dataset: "all-Bangladeshi-medicines" by Mahadi Hassan (Mahadih534), hosted on Hugging Face Datasets (tagged CC-BY-2.0).*
- **Safety Framing**: All audit outputs and prototype interfaces must retain the required disclaimer: *Decision-support prototype only; not clinical advice or a medical device.*
