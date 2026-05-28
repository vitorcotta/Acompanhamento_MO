import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "acompanhamento.db"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def _add_column_if_missing(table: str, column: str, ddl: str) -> bool:
    insp = inspect(engine)
    if not insp.has_table(table):
        return False
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return False
    with engine.connect() as conn:
        conn.execute(text(ddl))
        conn.commit()
    return True


def migrate_schema() -> bool:
    """Retorna True se lancamentos precisam ser reimportados."""
    needs_reimport = False
    if _add_column_if_missing(
        "lancamentos",
        "divisao",
        "ALTER TABLE lancamentos ADD COLUMN divisao VARCHAR(128) "
        "NOT NULL DEFAULT '(sem divisão)'",
    ):
        needs_reimport = True
    if _add_column_if_missing(
        "lancamentos",
        "despesa",
        "ALTER TABLE lancamentos ADD COLUMN despesa VARCHAR(32) NOT NULL DEFAULT ''",
    ):
        needs_reimport = True
    return needs_reimport


def clear_all_data():
    from models import Arquivo, Lancamento, Orcamento, OrcamentoArquivo

    with SessionLocal() as db:
        db.query(Lancamento).delete()
        db.query(Arquivo).delete()
        db.query(Orcamento).delete()
        db.query(OrcamentoArquivo).delete()
        db.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
