import io
import json
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from models import Arquivo, Lancamento, Orcamento
from services import MESES_NOME

COLUNAS_NOVAS = ["Nova Despesa", "Nova Divisão"]


def list_destinos(db: Session, exercicio: int, mes: int) -> list[dict]:
    combos: dict[tuple[str, str, str], dict] = {}

    def add(despesa: str, equipe: str, divisao: str) -> None:
        despesa = (despesa or "").strip()
        equipe = (equipe or "").strip() or despesa
        divisao = (divisao or "").strip() or "(sem divisão)"
        if not divisao:
            return
        key = (despesa, equipe, divisao)
        if key not in combos:
            rotulo = f"{despesa} · {equipe} · {divisao}" if despesa else f"{equipe} · {divisao}"
            combos[key] = {
                "despesa": despesa,
                "equipe": equipe,
                "divisao": divisao,
                "rotulo": rotulo,
            }

    orc_rows = (
        db.query(Orcamento.despesa, Orcamento.equipe, Orcamento.divisao)
        .filter(Orcamento.exercicio == exercicio, Orcamento.mes == mes)
        .distinct()
        .all()
    )
    for r in orc_rows:
        add(r.despesa, r.equipe, r.divisao)

    real_rows = (
        db.query(Lancamento.despesa, Lancamento.equipe, Lancamento.divisao)
        .filter(Lancamento.exercicio == exercicio, Lancamento.mes == mes)
        .distinct()
        .all()
    )
    for r in real_rows:
        add(r.despesa, r.equipe, r.divisao)

    return sorted(
        combos.values(),
        key=lambda x: (x["divisao"], x["equipe"], x["despesa"]),
    )


def list_lancamentos(
    db: Session,
    exercicio: int,
    mes: int,
    *,
    divisao: str | None = None,
    busca: str | None = None,
) -> list[dict]:
    q = db.query(Lancamento).filter(
        Lancamento.exercicio == exercicio,
        Lancamento.mes == mes,
    )
    if divisao:
        q = q.filter(Lancamento.divisao == divisao)
    if busca:
        termo = f"%{busca.strip()}%"
        q = q.filter(
            (Lancamento.colaborador.ilike(termo))
            | (Lancamento.equipe.ilike(termo))
            | (Lancamento.despesa.ilike(termo))
        )
    rows = q.order_by(
        Lancamento.divisao,
        Lancamento.equipe,
        Lancamento.colaborador,
        Lancamento.id,
    ).all()
    return [
        {
            "id": r.id,
            "despesa": r.despesa,
            "equipe": r.equipe,
            "divisao": r.divisao,
            "colaborador": r.colaborador,
            "valor": round(float(r.valor), 2),
            "origem": r.origem,
            "is_adm": r.is_adm,
            "tem_linha_completa": bool(r.dados_linha),
        }
        for r in rows
    ]


def _ajuste_alterou(l: Lancamento, aj: dict[str, str]) -> bool:
    nova_despesa = aj.get("nova_despesa", "").strip()
    nova_divisao = aj.get("nova_divisao", "").strip()
    nova_equipe = aj.get("nova_equipe", "").strip()
    if nova_despesa != (l.despesa or "").strip():
        return True
    if nova_divisao != (l.divisao or "").strip():
        return True
    if nova_equipe and nova_equipe != (l.equipe or "").strip():
        return True
    return False


def _parse_colunas_arquivo(arquivo: Arquivo | None) -> list[str]:
    if not arquivo or not arquivo.colunas_json:
        return []
    try:
        cols = json.loads(arquivo.colunas_json)
        if isinstance(cols, list):
            return [str(c) for c in cols]
    except json.JSONDecodeError:
        pass
    return []


def _parse_dados_linha(l: Lancamento) -> dict[str, Any]:
    if not l.dados_linha:
        return {}
    try:
        data = json.loads(l.dados_linha)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()}
    except json.JSONDecodeError:
        pass
    return {}


def _fallback_linha_minima(l: Lancamento, mes: int) -> dict[str, Any]:
    return {
        "Despesa": l.despesa,
        "Descrição Despesa": l.equipe,
        "Divisão": l.divisao,
        "Nome": l.colaborador,
        "Valor realizado rateio": round(float(l.valor), 2),
        "Período contábil": mes,
        "Sistema de origem": l.origem,
        "Exercício": l.exercicio,
    }


def _montar_colunas_export(arquivos_cols: list[list[str]], orig: dict[str, Any]) -> list[str]:
    vistos: set[str] = set()
    ordem: list[str] = []
    for cols in arquivos_cols:
        for c in cols:
            if c not in vistos:
                vistos.add(c)
                ordem.append(c)
    for c in orig:
        if c not in vistos:
            vistos.add(c)
            ordem.append(c)
    return ordem


def _linha_export(
    l: Lancamento,
    aj: dict[str, str],
    colunas_origem: list[str],
) -> dict[str, Any]:
    orig = _parse_dados_linha(l)
    if not orig:
        orig = _fallback_linha_minima(l, l.mes)

    if not colunas_origem:
        colunas_origem = list(orig.keys())

    row: dict[str, Any] = {
        "Nova Despesa": aj["nova_despesa"] or l.despesa,
        "Nova Divisão": aj["nova_divisao"] or l.divisao,
    }
    for col in colunas_origem:
        if col in COLUNAS_NOVAS:
            continue
        row[col] = orig.get(col, "")
    return row


def exportar_ajustes_xlsx(
    db: Session,
    exercicio: int,
    mes: int,
    ajustes_payload: list[dict[str, Any]],
) -> tuple[bytes, str]:
    if not ajustes_payload:
        raise ValueError("Nenhum ajuste informado.")

    por_id: dict[int, dict[str, str]] = {}
    for item in ajustes_payload:
        lid = int(item["id"])
        por_id[lid] = {
            "nova_despesa": str(item.get("nova_despesa", "")).strip(),
            "nova_divisao": str(item.get("nova_divisao", "")).strip(),
            "nova_equipe": str(item.get("nova_equipe", "")).strip(),
        }

    rows_db = db.query(Lancamento).filter(Lancamento.id.in_(por_id.keys())).all()
    by_id = {r.id: r for r in rows_db}

    sem_dados = [lid for lid in por_id if by_id.get(lid) and not by_id[lid].dados_linha]
    if sem_dados:
        raise ValueError(
            "Algumas linhas não têm o Excel original salvo. Clique em Reimportar "
            "para recarregar os realizados com todas as colunas e tente exportar de novo."
        )

    arquivo_cache: dict[int, Arquivo | None] = {}
    todas_colunas_arquivo: list[list[str]] = []
    export_rows: list[dict] = []

    for lid, aj in por_id.items():
        l = by_id.get(lid)
        if not l or not _ajuste_alterou(l, aj):
            continue

        if l.arquivo_id not in arquivo_cache:
            arquivo_cache[l.arquivo_id] = db.get(Arquivo, l.arquivo_id)
        arq = arquivo_cache[l.arquivo_id]
        cols_arq = _parse_colunas_arquivo(arq)
        if cols_arq:
            todas_colunas_arquivo.append(cols_arq)

        export_rows.append(_linha_export(l, aj, cols_arq))

    if not export_rows:
        raise ValueError(
            "Nenhuma linha com alteração efetiva. Confira destino diferente do original."
        )

    colunas_origem = _montar_colunas_export(todas_colunas_arquivo, export_rows[0])
    colunas_finais = COLUNAS_NOVAS + [
        c for c in colunas_origem if c not in COLUNAS_NOVAS
    ]

    for i, row in enumerate(export_rows):
        export_rows[i] = {c: row.get(c, "") for c in colunas_finais}

    df = pd.DataFrame(export_rows, columns=colunas_finais)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Alterações")
    buf.seek(0)
    mes_label = MESES_NOME.get(mes, str(mes))
    nome = f"Realocacao_MO_{exercicio}_{mes_label}.xlsx"
    return buf.getvalue(), nome
