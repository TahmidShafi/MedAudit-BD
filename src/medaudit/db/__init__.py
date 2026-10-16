from medaudit.db.build import build_database
from medaudit.db.schema import SCHEMA_DDL


def __getattr__(name: str):
    if name in ("ensure_database", "is_database_complete"):
        import medaudit.db.bootstrap as b
        return getattr(b, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["SCHEMA_DDL", "build_database", "ensure_database", "is_database_complete"]


