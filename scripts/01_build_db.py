"""Script 01: Build SQLite database (data/processed/medaudit.db) from ingested dataset."""

import sys
from medaudit.config import PROJECT_ROOT
from medaudit.db.build import build_database


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 70)
    print("BUILDING SQLITE DATABASE: data/processed/medaudit.db")
    print("=" * 70)

    res = build_database()

    print(f"\nDatabase successfully created at: {res['db_path']}")
    print(f"Build time: {res['elapsed_seconds']:.2f} seconds\n")

    print(f"{'Table Name':<25} {'Row Count':<15}")
    print("-" * 40)
    for table, count in res["counts"].items():
        print(f"{table:<25} {count:<15,}")
    print("=" * 70)


if __name__ == "__main__":
    main()
