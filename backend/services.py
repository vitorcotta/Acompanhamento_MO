from datetime import date, datetime

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from models import Arquivo, Lancamento, Orcamento, OrcamentoArquivo, Pessoa

MESES_NOME = {
    1: "Jan",
    2: "Fev",
    3: "Mar",
    4: "Abr",
    5: "Mai",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Set",
    10: "Out",
    11: "Nov",
    12: "Dez",
}


def list_exercicios(db: Session) -> list[int]:
    rows = db.query(Lancamento.exercicio).distinct().order_by(Lancamento.exercicio.desc())
    return [r[0] for r in rows.all()]


def list_divisoes(db: Session, exercicio: int) -> list[str]:
    rows = (
        db.query(Lancamento.divisao)
        .filter(Lancamento.exercicio == exercicio)
        .distinct()
        .order_by(Lancamento.divisao)
        .all()
    )
    return [r[0] for r in rows]


def _filter_divisao(q, divisao: str | None):
    if divisao:
        return q.filter(Lancamento.divisao == divisao)
    return q


def list_arquivos(db: Session) -> list[dict]:
    realizados = [
        {
            "id": a.id,
            "tipo": "realizado",
            "nome": a.nome,
            "exercicio": a.exercicio,
            "meses": a.meses,
            "total_linhas": a.total_linhas,
            "importado_em": a.importado_em.isoformat(),
        }
        for a in db.query(Arquivo).order_by(Arquivo.importado_em.desc()).all()
    ]
    orcamentos = [
        {
            "id": a.id,
            "tipo": "orcamento",
            "nome": a.nome,
            "exercicio": a.exercicio,
            "meses": "Jan–Dez",
            "total_linhas": a.total_linhas,
            "importado_em": a.importado_em.isoformat(),
        }
        for a in db.query(OrcamentoArquivo).order_by(OrcamentoArquivo.importado_em.desc()).all()
    ]
    return sorted(
        realizados + orcamentos,
        key=lambda x: x["importado_em"],
        reverse=True,
    )


def resumo_mensal(db: Session, exercicio: int, divisao: str | None = None) -> list[dict]:
    adm_valor = func.sum(case((Lancamento.is_adm, Lancamento.valor), else_=0.0))
    time_valor = func.sum(case((~Lancamento.is_adm, Lancamento.valor), else_=0.0))
    total = func.sum(Lancamento.valor)

    q = db.query(
        Lancamento.mes,
        total.label("total"),
        adm_valor.label("adm"),
        time_valor.label("time"),
    ).filter(Lancamento.exercicio == exercicio)
    q = _filter_divisao(q, divisao)
    rows = q.group_by(Lancamento.mes).order_by(Lancamento.mes).all()

    result = []
    prev_total = None
    for mes, total_v, adm_v, time_v in rows:
        pct_adm = (adm_v / total_v * 100) if total_v else 0
        variacao = None
        if prev_total is not None and prev_total:
            variacao = (total_v - prev_total) / prev_total * 100
        result.append(
            {
                "mes": mes,
                "mes_label": MESES_NOME.get(mes, str(mes)),
                "total": round(total_v, 2),
                "adm": round(adm_v, 2),
                "time": round(time_v, 2),
                "pct_adm": round(pct_adm, 1),
                "variacao_total_pct": round(variacao, 1) if variacao is not None else None,
            }
        )
        prev_total = total_v
    return result


def resumo_divisoes_mensal(db: Session, exercicio: int) -> dict:
    rows = (
        db.query(
            Lancamento.mes,
            Lancamento.divisao,
            func.sum(Lancamento.valor).label("valor"),
        )
        .filter(Lancamento.exercicio == exercicio)
        .group_by(Lancamento.mes, Lancamento.divisao)
        .all()
    )

    meses = sorted({r.mes for r in rows})
    divisoes = sorted({r.divisao for r in rows})
    grid = {d: {m: 0.0 for m in meses} for d in divisoes}
    for mes, divisao, valor in rows:
        grid[divisao][mes] = round(float(valor), 2)

    total_geral = sum(sum(grid[d].values()) for d in divisoes)
    series = []
    for divisao in divisoes:
        valores = [grid[divisao][m] for m in meses]
        total_ano = round(sum(valores), 2)
        pct_ano = round(total_ano / total_geral * 100, 1) if total_geral else 0.0
        series.append(
            {
                "divisao": divisao,
                "valores": valores,
                "total_ano": total_ano,
                "pct_ano": pct_ano,
            }
        )

    return {
        "meses": [{"num": m, "label": MESES_NOME.get(m, str(m))} for m in meses],
        "divisoes": divisoes,
        "series": series,
    }


def _build_pivot(rows, label_fn) -> dict:
    meses = sorted({r.mes for r in rows})
    linhas = sorted({label_fn(r) for r in rows})

    grid: dict[str, dict] = {}
    for linha in linhas:
        grid[linha] = {
            "meses": {m: {"adm": 0.0, "time": 0.0, "total": 0.0} for m in meses},
            "total_ano": {"adm": 0.0, "time": 0.0, "total": 0.0},
        }

    for row in rows:
        label = label_fn(row)
        bucket = "adm" if row.is_adm else "time"
        cell = grid[label]["meses"][row.mes]
        cell[bucket] += row.valor
        cell["total"] += row.valor
        grid[label]["total_ano"][bucket] += row.valor
        grid[label]["total_ano"]["total"] += row.valor

    for linha in grid:
        for m in meses:
            for key in ("adm", "time", "total"):
                grid[linha]["meses"][m][key] = round(grid[linha]["meses"][m][key], 2)
        for key in ("adm", "time", "total"):
            grid[linha]["total_ano"][key] = round(grid[linha]["total_ano"][key], 2)

    variacoes: dict[str, dict] = {}
    for linha, data in grid.items():
        variacoes[linha] = {}
        for i, mes in enumerate(meses):
            if i == 0:
                variacoes[linha][mes] = None
                continue
            prev = data["meses"][meses[i - 1]]["total"]
            cur = data["meses"][mes]["total"]
            variacoes[linha][mes] = (
                round((cur - prev) / prev * 100, 1) if prev else None
            )

    return {
        "meses": [{"num": m, "label": MESES_NOME.get(m, str(m))} for m in meses],
        "linhas": linhas,
        "grid": grid,
        "variacoes": variacoes,
    }


def list_meses(db: Session, exercicio: int) -> list[dict]:
    rows = (
        db.query(Lancamento.mes)
        .filter(Lancamento.exercicio == exercicio)
        .distinct()
        .order_by(Lancamento.mes)
        .all()
    )
    return [{"num": r[0], "label": MESES_NOME.get(r[0], str(r[0]))} for r in rows]


def comparar_meses(
    db: Session, exercicio: int, meses: list[int], dimensao: str
) -> dict:
    if dimensao not in ("equipe", "pessoa", "divisao"):
        raise ValueError("dimensao deve ser equipe, pessoa ou divisao")
    meses_unicos = list(dict.fromkeys(meses))
    if len(meses_unicos) < 2 or len(meses_unicos) > 3:
        raise ValueError("Selecione 2 ou 3 meses distintos")

    dim_map = {
        "equipe": (Lancamento.equipe, Lancamento.equipe),
        "pessoa": (Lancamento.colaborador, Lancamento.colaborador),
        "divisao": (Lancamento.divisao, Lancamento.divisao),
    }
    col, group_col = dim_map[dimensao]

    q = db.query(
        group_col.label("rotulo"),
        Lancamento.mes,
        Lancamento.is_adm,
        func.sum(Lancamento.valor).label("valor"),
    ).filter(
        Lancamento.exercicio == exercicio,
        Lancamento.mes.in_(meses_unicos),
    )
    if dimensao == "pessoa":
        q = q.filter(Lancamento.colaborador != "")
    rows = q.group_by(group_col, Lancamento.mes, Lancamento.is_adm).all()

    rotulos = sorted({r.rotulo for r in rows})
    grid: dict[str, dict[int, dict]] = {
        r: {m: {"adm": 0.0, "time": 0.0, "total": 0.0} for m in meses_unicos}
        for r in rotulos
    }

    for row in rows:
        bucket = "adm" if row.is_adm else "time"
        cell = grid[row.rotulo][row.mes]
        cell[bucket] += row.valor
        cell["total"] += row.valor

    linhas = []
    for rotulo in rotulos:
        meses_data = {}
        for m in meses_unicos:
            c = grid[rotulo][m]
            total = round(c["total"], 2)
            pct_adm = round(c["adm"] / total * 100, 1) if total else 0.0
            meses_data[str(m)] = {
                "total": total,
                "adm": round(c["adm"], 2),
                "pct_adm": pct_adm,
            }

        deltas = []
        for i in range(1, len(meses_unicos)):
            prev_m = meses_unicos[i - 1]
            cur_m = meses_unicos[i]
            prev_v = meses_data[str(prev_m)]["total"]
            cur_v = meses_data[str(cur_m)]["total"]
            pct = round((cur_v - prev_v) / prev_v * 100, 1) if prev_v else None
            deltas.append(
                {
                    "de": prev_m,
                    "de_label": MESES_NOME.get(prev_m, str(prev_m)),
                    "para": cur_m,
                    "para_label": MESES_NOME.get(cur_m, str(cur_m)),
                    "valor_de": prev_v,
                    "valor_para": cur_v,
                    "delta_abs": round(cur_v - prev_v, 2),
                    "delta_pct": pct,
                }
            )

        linhas.append({"rotulo": rotulo, "meses": meses_data, "deltas": deltas})

    def _sort_key(linha: dict) -> tuple:
        if not linha["deltas"]:
            return (1, 0.0, linha["rotulo"].lower())
        pct = linha["deltas"][0].get("delta_pct")
        if pct is None:
            return (1, 0.0, linha["rotulo"].lower())
        # Maior Δ% primeiro: aumentos no topo, reduções embaixo
        return (0, -pct, linha["rotulo"].lower())

    linhas.sort(key=_sort_key)

    totais_por_mes = {}
    for m in meses_unicos:
        t = sum(grid[r][m]["total"] for r in rotulos)
        a = sum(grid[r][m]["adm"] for r in rotulos)
        totais_por_mes[str(m)] = {
            "total": round(t, 2),
            "pct_adm": round(a / t * 100, 1) if t else 0.0,
        }

    dim_labels = {
        "equipe": "Equipe (Descrição Despesa)",
        "pessoa": "Colaborador (Nome)",
        "divisao": "Divisão",
    }

    return {
        "dimensao": dimensao,
        "dimensao_label": dim_labels[dimensao],
        "meses": [
            {"num": m, "label": MESES_NOME.get(m, str(m))} for m in meses_unicos
        ],
        "linhas": linhas,
        "totais": totais_por_mes,
    }


def novidades_por_equipe(db: Session, exercicio: int, divisao: str | None = None) -> dict[str, dict]:
    """Colaboradores cuja primeira aparição na equipe, neste exercício, é o mês mais
    recente com lançamentos — possível sinal de alguém alocado vindo de outra área."""
    meses_q = db.query(Lancamento.mes).filter(Lancamento.exercicio == exercicio)
    meses_q = _filter_divisao(meses_q, divisao)
    meses = sorted({r[0] for r in meses_q.distinct().all()})
    if len(meses) < 2:
        return {}
    ultimo_mes = meses[-1]

    q = db.query(
        Lancamento.equipe,
        Lancamento.colaborador,
        func.min(Lancamento.mes).label("primeiro_mes"),
    ).filter(Lancamento.exercicio == exercicio, Lancamento.colaborador != "")
    q = _filter_divisao(q, divisao)
    rows = q.group_by(Lancamento.equipe, Lancamento.colaborador).all()

    resultado: dict[str, dict] = {}
    for r in rows:
        if r.primeiro_mes != ultimo_mes:
            continue
        bucket = resultado.setdefault(
            r.equipe,
            {
                "novos": [],
                "mes": ultimo_mes,
                "mes_label": MESES_NOME.get(ultimo_mes, str(ultimo_mes)),
            },
        )
        bucket["novos"].append(r.colaborador)
    return resultado


def pivot_equipes(db: Session, exercicio: int, divisao: str | None = None) -> dict:
    q = db.query(
        Lancamento.equipe,
        Lancamento.mes,
        Lancamento.is_adm,
        func.sum(Lancamento.valor).label("valor"),
    ).filter(Lancamento.exercicio == exercicio)
    q = _filter_divisao(q, divisao)
    rows = q.group_by(Lancamento.equipe, Lancamento.mes, Lancamento.is_adm).all()
    result = _build_pivot(rows, lambda r: r.equipe)
    result["equipes"] = result["linhas"]
    result["novidades_equipe"] = novidades_por_equipe(db, exercicio, divisao)
    return result


def pivot_colaboradores(
    db: Session, exercicio: int, equipe: str | None = None
) -> dict:
    q = db.query(
        Lancamento.colaborador,
        Lancamento.mes,
        Lancamento.is_adm,
        func.sum(Lancamento.valor).label("valor"),
    ).filter(
        Lancamento.exercicio == exercicio,
        Lancamento.colaborador != "",
    )
    if equipe:
        q = q.filter(Lancamento.equipe == equipe)
    rows = q.group_by(Lancamento.colaborador, Lancamento.mes, Lancamento.is_adm).all()
    result = _build_pivot(rows, lambda r: r.colaborador)
    _merge_cadastro_pessoas(result, db, exercicio, equipe)
    result["colaboradores"] = result["linhas"]
    if equipe:
        novidade_equipe = novidades_por_equipe(db, exercicio).get(equipe)
        if novidade_equipe:
            novos = set(novidade_equipe["novos"])
            result["novidades_pessoas"] = {
                nome: {
                    "tipo": "novo_na_equipe",
                    "label": f"Novo em {novidade_equipe['mes_label']} — confira a origem",
                }
                for nome in result["linhas"]
                if nome in novos
            }
    return result


def _status_pessoa(pessoa: Pessoa | None) -> dict:
    if pessoa is None:
        return {"tipo": "nao_cadastrado", "label": "Não cadastrado"}
    if not pessoa.pertence:
        return {"tipo": "nao_pertence", "label": "Não é da equipe"}
    if pessoa.data_saida:
        mes_label = MESES_NOME.get(pessoa.data_saida.month, str(pessoa.data_saida.month))
        return {"tipo": "saiu", "label": f"Saiu em {mes_label}/{pessoa.data_saida.year}"}
    return {"tipo": "ativo", "label": "Ativo"}


def _recalcula_variacao(result: dict, nome: str) -> None:
    meses_nums = [m["num"] for m in result["meses"]]
    row = result["grid"][nome]
    var: dict[int, float | None] = {}
    for i, mn in enumerate(meses_nums):
        if i == 0:
            var[mn] = None
            continue
        prev_v = row["meses"][meses_nums[i - 1]]["total"]
        cur_v = row["meses"][mn]["total"]
        var[mn] = round((cur_v - prev_v) / prev_v * 100, 1) if prev_v else None
    result["variacoes"][nome] = var


def _zera_apos_saida(result: dict, nome: str, data_saida: date, exercicio: int) -> None:
    if exercicio < data_saida.year:
        return
    mes_corte = data_saida.month if exercicio == data_saida.year else 1
    row = result["grid"][nome]
    zerou = False
    for m in result["meses"]:
        mes_num = m["num"]
        if mes_num >= mes_corte:
            cell = row["meses"][mes_num]
            if cell["total"] or cell["adm"] or cell["time"]:
                zerou = True
            row["meses"][mes_num] = {"adm": 0.0, "time": 0.0, "total": 0.0}
    if not zerou:
        return
    row["total_ano"] = {
        key: round(sum(row["meses"][m["num"]][key] for m in result["meses"]), 2)
        for key in ("adm", "time", "total")
    }
    _recalcula_variacao(result, nome)


def _merge_cadastro_pessoas(
    result: dict, db: Session, exercicio: int, equipe: str | None
) -> None:
    pessoas = {p.nome: p for p in db.query(Pessoa).all()}

    if equipe is None:
        nomes_existentes = set(result["linhas"])
        for nome, pessoa in pessoas.items():
            if pessoa.pertence and nome not in nomes_existentes:
                result["linhas"].append(nome)
                result["grid"][nome] = {
                    "meses": {
                        m["num"]: {"adm": 0.0, "time": 0.0, "total": 0.0}
                        for m in result["meses"]
                    },
                    "total_ano": {"adm": 0.0, "time": 0.0, "total": 0.0},
                }
                result["variacoes"][nome] = {m["num"]: None for m in result["meses"]}
        result["linhas"].sort()
        result["colaboradores"] = result["linhas"]

    for nome in result["linhas"]:
        pessoa = pessoas.get(nome)
        if pessoa and pessoa.pertence and pessoa.data_saida:
            _zera_apos_saida(result, nome, pessoa.data_saida, exercicio)

    result["status_pessoas"] = {
        nome: _status_pessoa(pessoas.get(nome)) for nome in result["linhas"]
    }


def _pessoa_dict(pessoa: Pessoa) -> dict:
    return {
        "id": pessoa.id,
        "nome": pessoa.nome,
        "pertence": pessoa.pertence,
        "data_saida": pessoa.data_saida.isoformat() if pessoa.data_saida else None,
        "observacao": pessoa.observacao,
    }


def list_pessoas(db: Session) -> list[dict]:
    pessoas = db.query(Pessoa).order_by(Pessoa.nome).all()
    return [_pessoa_dict(p) for p in pessoas]


def upsert_pessoa(
    db: Session,
    nome: str,
    pertence: bool,
    data_saida: str | None,
    observacao: str = "",
) -> dict:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Nome é obrigatório")
    saida = date.fromisoformat(data_saida) if data_saida else None

    pessoa = db.query(Pessoa).filter(Pessoa.nome == nome).first()
    if pessoa is None:
        pessoa = Pessoa(nome=nome, pertence=pertence, data_saida=saida, observacao=observacao)
        db.add(pessoa)
    else:
        pessoa.pertence = pertence
        pessoa.data_saida = saida
        pessoa.observacao = observacao
        pessoa.atualizado_em = datetime.utcnow()
    db.commit()
    db.refresh(pessoa)
    return _pessoa_dict(pessoa)


def delete_pessoa(db: Session, pessoa_id: int) -> None:
    pessoa = db.get(Pessoa, pessoa_id)
    if pessoa:
        db.delete(pessoa)
        db.commit()


_STATUS_PRIORIDADE = {
    "nao_pertence": 0,
    "nao_cadastrado": 1,
    "saiu": 2,
    "ativo": 3,
}


def lista_mensal_pessoas(
    db: Session, exercicio: int, mes: int, divisao: str | None = None
) -> list[dict]:
    """Lista consolidada por pessoa de quem foi alocado no mês, com o status de
    pertencimento — para validar um arquivo recém-importado. Valores aqui NÃO são
    zerados: é justamente o lugar para flagrar alguém que saiu (ou nunca foi da
    equipe) mas ainda apareceu com valor neste mês. Quando a pessoa tem lançamentos
    em mais de uma equipe/divisão/despesa no mesmo mês, as colunas mostram todas,
    separadas por " / ".
    """
    q = db.query(
        Lancamento.colaborador,
        Lancamento.equipe,
        Lancamento.divisao,
        Lancamento.despesa,
        Lancamento.valor,
    ).filter(
        Lancamento.exercicio == exercicio,
        Lancamento.mes == mes,
        Lancamento.colaborador != "",
    )
    if divisao:
        q = q.filter(Lancamento.divisao == divisao)
    rows = q.all()

    por_pessoa: dict[str, dict] = {}
    for r in rows:
        chave = " ".join(r.colaborador.split()).casefold()
        bucket = por_pessoa.setdefault(
            chave,
            {
                "nome": " ".join(r.colaborador.split()),
                "valor": 0.0,
                "equipes": set(),
                "divisoes": set(),
                "despesas": set(),
            },
        )
        bucket["valor"] += float(r.valor)
        bucket["equipes"].add(r.equipe)
        bucket["divisoes"].add(r.divisao)
        bucket["despesas"].add(r.despesa)

    pessoas = {p.nome: p for p in db.query(Pessoa).all()}
    novidades = novidades_por_equipe(db, exercicio, divisao)

    linhas = []
    for info in por_pessoa.values():
        nome = info["nome"]
        status = _status_pessoa(pessoas.get(nome))
        novidade = None
        for eq in info["equipes"]:
            bucket = novidades.get(eq)
            if bucket and nome in bucket["novos"]:
                novidade = f"Novo em {bucket['mes_label']}"
                break
        linhas.append(
            {
                "colaborador": nome,
                "equipe": " / ".join(sorted(info["equipes"])),
                "divisao": " / ".join(sorted(info["divisoes"])),
                "despesa": " / ".join(sorted(info["despesas"])),
                "valor": round(info["valor"], 2),
                "status": status,
                "novidade": novidade,
            }
        )

    linhas.sort(
        key=lambda x: (
            _STATUS_PRIORIDADE.get(x["status"]["tipo"], 3),
            0 if x["novidade"] else 1,
            x["colaborador"],
        )
    )
    return linhas


def colaboradores_nao_cadastrados(db: Session, exercicio: int) -> list[str]:
    nomes_lancamentos = {
        r[0]
        for r in db.query(Lancamento.colaborador)
        .filter(Lancamento.exercicio == exercicio, Lancamento.colaborador != "")
        .distinct()
        .all()
    }
    nomes_cadastrados = {r[0] for r in db.query(Pessoa.nome).all()}
    return sorted(nomes_lancamentos - nomes_cadastrados)


def colaboradores(db: Session, exercicio: int, mes: int | None = None) -> list[dict]:
    q = db.query(
        Lancamento.colaborador,
        Lancamento.equipe,
        Lancamento.is_adm,
        func.sum(Lancamento.valor).label("valor"),
    ).filter(Lancamento.exercicio == exercicio)
    if mes is not None:
        q = q.filter(Lancamento.mes == mes)
    rows = (
        q.group_by(Lancamento.colaborador, Lancamento.equipe, Lancamento.is_adm)
        .order_by(func.sum(Lancamento.valor).desc())
        .limit(200)
        .all()
    )
    return [
        {
            "colaborador": r.colaborador,
            "equipe": r.equipe,
            "is_adm": r.is_adm,
            "valor": round(r.valor, 2),
        }
        for r in rows
    ]


def comparativo_orcamento(
    db: Session, exercicio: int, divisao: str | None = None
) -> dict:
    real_rows = (
        db.query(
            Lancamento.despesa,
            Lancamento.divisao,
            func.max(Lancamento.equipe).label("equipe"),
            Lancamento.mes,
            func.sum(Lancamento.valor).label("valor"),
        )
        .filter(Lancamento.exercicio == exercicio, Lancamento.despesa != "")
        .group_by(Lancamento.despesa, Lancamento.divisao, Lancamento.mes)
    )
    if divisao:
        real_rows = real_rows.filter(Lancamento.divisao == divisao)
    real_rows = real_rows.all()

    orc_q = db.query(
        Orcamento.despesa,
        Orcamento.divisao,
        Orcamento.equipe,
        Orcamento.mes,
        Orcamento.valor,
    ).filter(Orcamento.exercicio == exercicio)
    if divisao:
        orc_q = orc_q.filter(Orcamento.divisao == divisao)
    orc_rows = orc_q.all()

    if not orc_rows:
        return {
            "tem_orcamento": False,
            "meses": [],
            "resumo_mensal": [],
            "linhas": [],
            "totais": None,
        }

    meses = sorted({r.mes for r in orc_rows} | {r.mes for r in real_rows})
    chaves: dict[tuple[str, str], dict] = {}

    def _linha(despesa: str, divisao_nome: str, equipe: str) -> dict:
        key = (despesa, divisao_nome)
        if key not in chaves:
            chaves[key] = {
                "despesa": despesa,
                "divisao": divisao_nome,
                "equipe": equipe,
                "meses": {
                    m: {"orcado": 0.0, "realizado": 0.0} for m in range(1, 13)
                },
                "total_ano": {"orcado": 0.0, "realizado": 0.0},
            }
        return chaves[key]

    for r in orc_rows:
        linha = _linha(r.despesa, r.divisao, r.equipe)
        linha["meses"][r.mes]["orcado"] += r.valor
        linha["total_ano"]["orcado"] += r.valor

    for r in real_rows:
        linha = _linha(r.despesa, r.divisao, r.equipe or r.despesa)
        linha["meses"][r.mes]["realizado"] += float(r.valor)
        linha["total_ano"]["realizado"] += float(r.valor)

    resumo_mensal = []
    for mes in meses:
        orcado = sum(chaves[k]["meses"][mes]["orcado"] for k in chaves)
        realizado = sum(chaves[k]["meses"][mes]["realizado"] for k in chaves)
        consumo = (realizado / orcado * 100) if orcado else None
        resumo_mensal.append(
            {
                "mes": mes,
                "mes_label": MESES_NOME.get(mes, str(mes)),
                "orcado": round(orcado, 2),
                "realizado": round(realizado, 2),
                "saldo": round(orcado - realizado, 2),
                "consumo_pct": round(consumo, 1) if consumo is not None else None,
            }
        )

    linhas = []
    for key in sorted(chaves, key=lambda k: (chaves[k]["divisao"], chaves[k]["equipe"])):
        item = chaves[key]
        for m in item["meses"]:
            for campo in ("orcado", "realizado"):
                item["meses"][m][campo] = round(item["meses"][m][campo], 2)
        for campo in ("orcado", "realizado"):
            item["total_ano"][campo] = round(item["total_ano"][campo], 2)
        o = item["total_ano"]["orcado"]
        r = item["total_ano"]["realizado"]
        item["total_ano"]["saldo"] = round(o - r, 2)
        item["total_ano"]["consumo_pct"] = round(r / o * 100, 1) if o else None
        linhas.append(item)

    tot_orcado = sum(x["total_ano"]["orcado"] for x in linhas)
    tot_real = sum(x["total_ano"]["realizado"] for x in linhas)

    return {
        "tem_orcamento": True,
        "meses": [{"num": m, "label": MESES_NOME.get(m, str(m))} for m in meses],
        "resumo_mensal": resumo_mensal,
        "linhas": linhas,
        "totais": {
            "orcado": round(tot_orcado, 2),
            "realizado": round(tot_real, 2),
            "saldo": round(tot_orcado - tot_real, 2),
            "consumo_pct": round(tot_real / tot_orcado * 100, 1) if tot_orcado else None,
        },
    }


def orcamento_equipe_anual(
    db: Session, exercicio: int, divisao: str | None = None
) -> dict:
    orc_q = db.query(
        Orcamento.equipe,
        Orcamento.mes,
        Orcamento.valor,
    ).filter(Orcamento.exercicio == exercicio)
    if divisao:
        orc_q = orc_q.filter(Orcamento.divisao == divisao)
    orc_rows = orc_q.all()

    if not orc_rows:
        return {
            "tem_orcamento": False,
            "meses": [],
            "linhas": [],
            "totais": None,
        }

    real_q = db.query(
        Lancamento.equipe,
        Lancamento.mes,
        func.sum(Lancamento.valor).label("valor"),
    ).filter(Lancamento.exercicio == exercicio)
    if divisao:
        real_q = real_q.filter(Lancamento.divisao == divisao)
    real_rows = real_q.group_by(Lancamento.equipe, Lancamento.mes).all()

    meses = sorted({r.mes for r in orc_rows} | {r.mes for r in real_rows})
    equipes: dict[str, dict] = {}

    def _linha(equipe: str) -> dict:
        if equipe not in equipes:
            equipes[equipe] = {
                "equipe": equipe,
                "meses": {m: {"orcado": 0.0, "realizado": 0.0} for m in range(1, 13)},
                "total_ano": {"orcado": 0.0, "realizado": 0.0},
            }
        return equipes[equipe]

    for r in orc_rows:
        linha = _linha(r.equipe)
        linha["meses"][r.mes]["orcado"] += r.valor
        linha["total_ano"]["orcado"] += r.valor

    for r in real_rows:
        linha = _linha(r.equipe or "")
        linha["meses"][r.mes]["realizado"] += float(r.valor)
        linha["total_ano"]["realizado"] += float(r.valor)

    linhas = []
    for equipe in sorted(equipes):
        item = equipes[equipe]
        for m in item["meses"]:
            for campo in ("orcado", "realizado"):
                item["meses"][m][campo] = round(item["meses"][m][campo], 2)
        for campo in ("orcado", "realizado"):
            item["total_ano"][campo] = round(item["total_ano"][campo], 2)
        o = item["total_ano"]["orcado"]
        r = item["total_ano"]["realizado"]
        item["total_ano"]["saldo"] = round(o - r, 2)
        item["total_ano"]["consumo_pct"] = round(r / o * 100, 1) if o else None
        linhas.append(item)

    tot_orcado = sum(x["total_ano"]["orcado"] for x in linhas)
    tot_real = sum(x["total_ano"]["realizado"] for x in linhas)

    return {
        "tem_orcamento": True,
        "meses": [{"num": m, "label": MESES_NOME.get(m, str(m))} for m in meses],
        "linhas": linhas,
        "totais": {
            "orcado": round(tot_orcado, 2),
            "realizado": round(tot_real, 2),
            "saldo": round(tot_orcado - tot_real, 2),
            "consumo_pct": round(tot_real / tot_orcado * 100, 1) if tot_orcado else None,
        },
    }


def comparativo_equipe_mes(
    db: Session, exercicio: int, mes: int, divisao: str | None = None
) -> dict:
    tem_orc = (
        db.query(Orcamento.id)
        .filter(Orcamento.exercicio == exercicio, Orcamento.mes == mes)
        .limit(1)
        .first()
    )
    if not tem_orc:
        return {
            "tem_orcamento": False,
            "mes": mes,
            "mes_label": MESES_NOME.get(mes, str(mes)),
            "linhas": [],
            "totais": None,
        }

    orc_q = (
        db.query(
            Orcamento.equipe,
            Orcamento.divisao,
            Orcamento.despesa,
            func.sum(Orcamento.valor).label("valor"),
        )
        .filter(Orcamento.exercicio == exercicio, Orcamento.mes == mes)
        .group_by(Orcamento.equipe, Orcamento.divisao, Orcamento.despesa)
    )
    if divisao:
        orc_q = orc_q.filter(Orcamento.divisao == divisao)
    orc_rows = orc_q.all()

    real_q = (
        db.query(
            Lancamento.equipe,
            Lancamento.divisao,
            Lancamento.despesa,
            func.sum(Lancamento.valor).label("valor"),
        )
        .filter(Lancamento.exercicio == exercicio, Lancamento.mes == mes)
        .group_by(Lancamento.equipe, Lancamento.divisao, Lancamento.despesa)
    )
    if divisao:
        real_q = real_q.filter(Lancamento.divisao == divisao)
    real_rows = real_q.all()

    grid: dict[tuple[str, str, str], dict] = {}

    def _cell(equipe: str, divisao_nome: str, despesa: str) -> dict:
        key = (equipe, divisao_nome, despesa)
        if key not in grid:
            grid[key] = {
                "equipe": equipe,
                "divisao": divisao_nome,
                "despesa": despesa,
                "orcado": 0.0,
                "realizado": 0.0,
            }
        return grid[key]

    for r in orc_rows:
        c = _cell(r.equipe, r.divisao, r.despesa)
        c["orcado"] += float(r.valor)

    for r in real_rows:
        c = _cell(r.equipe, r.divisao, r.despesa or "")
        c["realizado"] += float(r.valor)

    linhas = []
    for item in grid.values():
        orcado = round(item["orcado"], 2)
        realizado = round(item["realizado"], 2)
        delta_valor = round(realizado - orcado, 2)
        delta_pct = round(delta_valor / orcado * 100, 1) if orcado else None
        consumo_pct = round(realizado / orcado * 100, 1) if orcado else None
        linhas.append(
            {
                "equipe": item["equipe"],
                "divisao": item["divisao"],
                "despesa": item["despesa"],
                "orcado": orcado,
                "realizado": realizado,
                "delta_valor": delta_valor,
                "delta_pct": delta_pct,
                "consumo_pct": consumo_pct,
            }
        )

    linhas.sort(
        key=lambda x: (x["consumo_pct"] if x["consumo_pct"] is not None else -1),
        reverse=True,
    )

    tot_o = sum(x["orcado"] for x in linhas)
    tot_r = sum(x["realizado"] for x in linhas)
    delta_t = round(tot_r - tot_o, 2)

    return {
        "tem_orcamento": True,
        "mes": mes,
        "mes_label": MESES_NOME.get(mes, str(mes)),
        "linhas": linhas,
        "totais": {
            "orcado": round(tot_o, 2),
            "realizado": round(tot_r, 2),
            "delta_valor": delta_t,
            "delta_pct": round(delta_t / tot_o * 100, 1) if tot_o else None,
            "consumo_pct": round(tot_r / tot_o * 100, 1) if tot_o else None,
        },
    }
