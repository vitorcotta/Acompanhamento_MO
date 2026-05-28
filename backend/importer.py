import hashlib
import re
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from budget_importer import is_orcamento_file
from models import Arquivo, Lancamento

COLUMN_ALIASES = {
    "despesa": "despesa",
    "descricao despesa": "equipe",
    "descrição despesa": "equipe",
    "nome": "colaborador",
    "valor realizado rateio": "valor",
    "periodo contabil": "mes",
    "período contábil": "mes",
    "sistema de origem": "origem",
    "exercicio": "exercicio",
    "exercício": "exercicio",
    "divisão": "divisao",
    "divisao": "divisao",
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in COLUMN_ALIASES:
            mapping[col] = COLUMN_ALIASES[key]
    return df.rename(columns=mapping)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_excel(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=0)
    df = _normalize_columns(df)
    required = {"equipe", "colaborador", "valor", "mes", "origem"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Colunas obrigatórias ausentes em {path.name}: {', '.join(sorted(missing))}"
        )
    if "exercicio" not in df.columns:
        df["exercicio"] = None
    if "divisao" not in df.columns:
        df["divisao"] = "(sem divisão)"
    if "despesa" not in df.columns:
        df["despesa"] = ""

    df = df[list(required | {"exercicio", "divisao", "despesa"})].copy()
    df["equipe"] = df["equipe"].fillna("(sem equipe)").astype(str).str.strip()
    df["divisao"] = df["divisao"].fillna("(sem divisão)").astype(str).str.strip()
    df["despesa"] = df["despesa"].fillna("").astype(str).str.strip()
    df["colaborador"] = df["colaborador"].fillna("").astype(str).str.strip()
    df["origem"] = df["origem"].fillna("").astype(str).str.strip().str.upper()
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    df["mes"] = pd.to_numeric(df["mes"], errors="coerce").astype("Int64")
    df["exercicio"] = pd.to_numeric(df["exercicio"], errors="coerce")
    df = df.dropna(subset=["mes"])
    df["mes"] = df["mes"].astype(int)
    if df["exercicio"].notna().any():
        default_year = int(df["exercicio"].dropna().iloc[0])
    else:
        year_match = re.search(r"(20\d{2})", path.stem)
        default_year = int(year_match.group(1)) if year_match else 2026
    df["exercicio"] = int(default_year)
    df["is_adm"] = df["origem"] == "ADM"
    return df


def import_file(db: Session, path: Path, *, replace_periods: bool = True) -> Arquivo:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    content_hash = _file_hash(path)
    existing = db.query(Arquivo).filter(Arquivo.nome == path.name).first()
    if existing and existing.hash_conteudo == content_hash:
        return existing

    df = parse_excel(path)
    exercicio = int(df["exercicio"].iloc[0])
    meses = sorted(df["mes"].unique().tolist())
    meses_str = ",".join(str(m) for m in meses)

    if replace_periods:
        for mes in meses:
            db.query(Lancamento).filter(
                Lancamento.exercicio == exercicio,
                Lancamento.mes == mes,
            ).delete(synchronize_session=False)

    if existing:
        db.query(Lancamento).filter(Lancamento.arquivo_id == existing.id).delete(
            synchronize_session=False
        )
        db.delete(existing)
        db.flush()

    arquivo = Arquivo(
        nome=path.name,
        hash_conteudo=content_hash,
        exercicio=exercicio,
        meses=meses_str,
        total_linhas=len(df),
    )
    db.add(arquivo)
    db.flush()

    registros = [
        Lancamento(
            arquivo_id=arquivo.id,
            exercicio=int(row.exercicio),
            mes=int(row.mes),
            despesa=row.despesa,
            equipe=row.equipe,
            divisao=row.divisao,
            colaborador=row.colaborador,
            valor=float(row.valor),
            origem=row.origem,
            is_adm=bool(row.is_adm),
        )
        for row in df.itertuples(index=False)
    ]
    db.bulk_save_objects(registros)
    db.commit()
    db.refresh(arquivo)
    return arquivo


def import_directory(db: Session, directory: Path) -> list[Arquivo]:
    imported: list[Arquivo] = []
    if not directory.exists():
        return imported
    for path in sorted(directory.glob("*.xlsx")) + sorted(directory.glob("*.XLSX")):
        if is_orcamento_file(path):
            continue
        try:
            imported.append(import_file(db, path))
        except Exception as exc:
            print(f"[import] ignorando {path.name}: {exc}")
    return imported
