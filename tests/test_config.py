"""Basic configuration and environment sanity test."""

from medaudit.config import SEED, PROJECT_ROOT, RAW_DATA_DIR


def test_seed_value():
    assert SEED == 42


def test_project_root_exists():
    assert PROJECT_ROOT.exists()
    assert (PROJECT_ROOT / "pyproject.toml").exists()
