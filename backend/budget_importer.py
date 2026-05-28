import hashlib
import re
import unicodedata
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from models import Orcamento, OrcamentoArquivo

MESES_ORCAMENTO = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _nome_normalizado(path: Path) -> str:
    nome = unicodedata.normalize("NFKD", path.stem)
    return nome.encode("ascii", "ignore").decode().lower()


def is_orcamento_file(path: Path) -> bool:
    return "orcamento" in _nome_normalizado(path)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _mes_numero(coluna: str) -> int | None:
    key = unicodedata.normalize("NFKD", str(coluna).strip())
    key = key.encode("ascii", "ignore").decode().lower()
    return MESES_ORCAMENTO.get(key)


def _find_orcamento_arquivo(db: Session, nome: str) -> OrcamentoArquivo | None:
    alvo = _nome_normalizado(Path(nome))
    for arq in db.query(OrcamentoArquivo).all():
        if _nome_normalizado(Path(arq.nome)) == alvo:
            return arq
    return None


def parse_orcamento(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=0)
    col_map = {str(c).strip().lower(): c for c in df.columns}

    despesa_col = col_map.get("despesa")
    divisao_col = col_map.get("divisão") or col_map.get("divisao")
    equipe_col = col_map.get("descrição despesa") or col_map.get("descricao despesa")
    exercicio_col = col_map.get("exercício") or col_map.get("exercicio")

    if not despesa_col or not divisao_col:
        raise ValueError(
            f"Orçamento {path.name}: colunas Despesa e Divisão são obrigatórias."
        )

    mes_cols = []
    for col in df.columns:
        mes = _mes_numero(col)
        if mes is not None:
            mes_cols.append((col, mes))

    if not mes_cols:
        raise ValueError(f"Orçamento {path.name}: nenhuma coluna de mês (Jan–Dez) encontrada.")

    if exercicio_col:
        exercicio = int(pd.to_numeric(df[exercicio_col], errors="coerce").dropna().iloc[0])
    else:
        year_match = re.search(r"(20\d{2})", path.stem)
        exercicio = int(year_match.group(1)) if year_match else 2026

    work = df[[despesa_col, divisao_col] + [c for c, _ in mes_cols]].copy()
    if equipe_col:
        work[equipe_col] = df[equipe_col]
    work[despesa_col] = work[despesa_col].fillna("").astype(str).str.strip()
    work[divisao_col] = work[divisao_col].fillna("(sem divisão)").astype(str).str.strip()

    agg = work.groupby([despesa_col, divisao_col], as_index=False)[[c for c, _ in mes_cols]].sum()
    if equipe_col:
        equipes = (
            df.groupby([despesa_col, divisao_col])[equipe_col]
            .first()
            .reset_index()
        )
        equipes[equipe_col] = equipes[equipe_col].fillna("").astype(str).str.strip()
        agg = agg.merge(equipes, on=[despesa_col, divisao_col])
    else:
        equipe_col = "_equipe"
        agg[equipe_col] = agg[despesa_col]

    records = []
    for _, row in agg.iterrows():
        despesa = str(row[despesa_col]).strip()
        divisao = str(row[divisao_col]).strip()
        equipe = str(row[equipe_col]).strip() if equipe_col in row.index else ""
        for col, mes in mes_cols:
            valor = pd.to_numeric(row[col], errors="coerce")
            if pd.isna(valor):
                valor = 0.0
            records.append(
                {
                    "exercicio": exercicio,
                    "despesa": despesa,
                    "equipe": equipe or despesa,
                    "divisao": divisao,
                    "mes": mes,
                    "valor": float(valor),
                }
            )

    return pd.DataFrame(records)


def import_orcamento_file(
    db: Session, path: Path, *, force: bool = False
) -> OrcamentoArquivo:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    content_hash = _file_hash(path)
    existing = _find_orcamento_arquivo(db, path.name)
    if existing and existing.hash_conteudo == content_hash and not force:
        return existing

    df = parse_orcamento(path)
    exercicio = int(df["exercicio"].iloc[0])

    db.query(Orcamento).filter(Orcamento.exercicio == exercicio).delete(
        synchronize_session=False
    )
    if existing:
        db.query(Orcamento).filter(Orcamento.arquivo_id == existing.id).delete(
            synchronize_session=False
        )
        db.delete(existing)
        db.flush()

    arquivo = OrcamentoArquivo(
        nome=path.name,
        hash_conteudo=content_hash,
        exercicio=exercicio,
        total_linhas=len(df),
    )
    db.add(arquivo)
    db.flush()

    db.bulk_save_objects(
        [
            Orcamento(
                arquivo_id=arquivo.id,
                exercicio=int(row.exercicio),
                despesa=row.despesa,
                equipe=row.equipe,
                divisao=row.divisao,
                mes=int(row.mes),
                valor=float(row.valor),
            )
            for row in df.itertuples(index=False)
        ]
    )
    db.commit()
    db.refresh(arquivo)
    return arquivo


def import_orcamento_directory(db: Session, directory: Path) -> list[OrcamentoArquivo]:
    imported: list[OrcamentoArquivo] = []
    if not directory.exists():
        return imported
    for path in sorted(directory.glob("*.xlsx")) + sorted(directory.glob("*.XLSX")):
        if not is_orcamento_file(path):
            continue
        try:
            imported.append(import_orcamento_file(db, path))
        except Exception as exc:
            print(f"[orcamento] ignorando {path.name}: {exc}")
    return imported


def delete_orcamento_arquivo(db: Session, arquivo_id: int) -> bool:
    arquivo = db.get(OrcamentoArquivo, arquivo_id)
    if not arquivo:
        return False
    db.query(Orcamento).filter(Orcamento.arquivo_id == arquivo_id).delete(
        synchronize_session=False
    )
    db.delete(arquivo)
    db.commit()
    return True
