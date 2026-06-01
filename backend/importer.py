import hashlib
import json
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

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
    "valor contábil real.": "valor",
    "valor contabil real.": "valor",
    "valor contábil real": "valor",
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


def _cell_to_json(val: Any) -> Any:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, pd.Timestamp):
        return val.isoformat()
    if isinstance(val, (datetime, date, time)):
        return val.isoformat()
    if isinstance(val, float) and val == int(val):
        return int(val)
    if hasattr(val, "item"):
        try:
            return val.item()
        except (ValueError, AttributeError):
            pass
    return val


def _row_original_dict(df_raw: pd.DataFrame, idx: int) -> dict[str, Any]:
    row = df_raw.iloc[idx]
    return {str(col).strip(): _cell_to_json(row[col]) for col in df_raw.columns}


def _lookup_field(row_dict: dict[str, Any], *aliases: str) -> Any:
    lower = {str(k).lower().strip(): v for k, v in row_dict.items()}
    for alias in aliases:
        key = alias.lower().strip()
        if key in lower:
            return lower[key]
    return None


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_excel(path: Path) -> tuple[list[str], list[dict]]:
    """Retorna ordem das colunas originais e linhas prontas para gravar no banco."""
    df_raw = pd.read_excel(path, sheet_name=0)
    colunas = [str(c).strip() for c in df_raw.columns]
    df = _normalize_columns(df_raw.copy())

    required = {"equipe", "colaborador", "valor", "mes", "origem"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Colunas obrigatórias ausentes em {path.name}: {', '.join(sorted(missing))}. "
            f"Confira se o arquivo tem valor (ex.: Valor realizado rateio ou Valor contábil real.), "
            f"Nome, Descrição Despesa, Período contábil e Sistema de origem."
        )

    if "exercicio" not in df.columns:
        df["exercicio"] = None
    if "divisao" not in df.columns:
        df["divisao"] = "(sem divisão)"
    if "despesa" not in df.columns:
        df["despesa"] = ""

    if df["exercicio"].notna().any():
        default_year = int(df["exercicio"].dropna().iloc[0])
    else:
        year_match = re.search(r"(20\d{2})", path.stem)
        default_year = int(year_match.group(1)) if year_match else 2026

    linhas: list[dict] = []
    for idx in range(len(df)):
        row_norm = df.iloc[idx]
        mes_val = pd.to_numeric(row_norm["mes"], errors="coerce")
        if pd.isna(mes_val):
            continue

        orig = _row_original_dict(df_raw, idx)
        equipe = str(row_norm.get("equipe", "") or "").strip() or "(sem equipe)"
        divisao = str(row_norm.get("divisao", "") or "").strip() or "(sem divisão)"
        despesa = str(row_norm.get("despesa", "") or "").strip()
        colaborador = str(row_norm.get("colaborador", "") or "").strip()
        origem = str(row_norm.get("origem", "") or "").strip().upper()
        valor = float(pd.to_numeric(row_norm["valor"], errors="coerce") or 0.0)

        linhas.append(
            {
                "exercicio": default_year,
                "mes": int(mes_val),
                "despesa": despesa,
                "equipe": equipe,
                "divisao": divisao,
                "colaborador": colaborador,
                "valor": valor,
                "origem": origem,
                "is_adm": origem == "ADM",
                "dados_linha": json.dumps(orig, ensure_ascii=False),
            }
        )

    if not linhas:
        raise ValueError(f"Nenhuma linha válida em {path.name}.")

    return colunas, linhas


def import_file(db: Session, path: Path, *, replace_periods: bool = True) -> Arquivo:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    content_hash = _file_hash(path)
    existing = db.query(Arquivo).filter(Arquivo.nome == path.name).first()
    if existing and existing.hash_conteudo == content_hash:
        return existing

    colunas, linhas = parse_excel(path)
    exercicio = int(linhas[0]["exercicio"])
    meses = sorted({ln["mes"] for ln in linhas})
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
        total_linhas=len(linhas),
        colunas_json=json.dumps(colunas, ensure_ascii=False),
    )
    db.add(arquivo)
    db.flush()

    registros = [
        Lancamento(
            arquivo_id=arquivo.id,
            exercicio=ln["exercicio"],
            mes=ln["mes"],
            despesa=ln["despesa"],
            equipe=ln["equipe"],
            divisao=ln["divisao"],
            colaborador=ln["colaborador"],
            valor=ln["valor"],
            origem=ln["origem"],
            is_adm=ln["is_adm"],
            dados_linha=ln["dados_linha"],
        )
        for ln in linhas
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
