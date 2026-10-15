"""MedAudit BD configuration and global constants."""

from pathlib import Path

# Seed pinned per PROJECT_BRIEF.md Ground Rule 6
SEED: int = 42

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
DOCS_DIR = PROJECT_ROOT / "docs"

# Hugging Face dataset identifier
HF_DATASET_NAME: str = "Mahadih534/all-Bangladeshi-medicines"
