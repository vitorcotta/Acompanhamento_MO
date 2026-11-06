"""MCP server para o Acompanhamento MO.

Expõe ao Claude Desktop os dados de orçado x realizado (por linha, por divisão e
por mês) para apoiar análise de equalização — sem nunca mandar o nome real de
nenhum colaborador para o modelo. Os dados vêm da própria API do app (não lê o
banco diretamente), então reaproveita toda a lógica de orçamento e cadastro já
existente no backend.
"""

import hashlib
import os
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer

API_BASE = os.environ.get("MO_API_BASE", "http://localhost:8000").rstrip("/")
SALT_FILE = Path(
    os.environ.get("MO_MCP_SALT_FILE", str(Path.home() / ".acompanhamento_mo_mcp_salt"))
)


def _get_salt() -> str:
    if SALT_FILE.exists():
        return SALT_FILE.read_text().strip()
    salt = os.urandom(16).hex()
    SALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SALT_FILE.write_text(salt)
    return salt


_SALT = _get_salt()


def _anonimizar(nome: str) -> str:
    """Pseudônimo estável e não-reversível por colaborador (mesmo nome real sempre
    vira o mesmo pseudônimo, mas o inverso é inviável sem o salt local)."""
    if not nome:
        return nome
    digest = hashlib.sha256(f"{_SALT}:{nome.strip().lower()}".encode()).hexdigest()[:6].upper()
    return f"Colaborador-{digest}"


def _get(path: str, params: dict | None = None) -> dict:
    resp = httpx.get(f"{API_BASE}{path}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


mcp = MCPServer("acompanhamento-mo")


@mcp.tool()
def listar_exercicios() -> dict:
    """Lista os exercícios (anos) com dados disponíveis no Acompanhamento MO."""
    return _get("/api/exercicios")


@mcp.tool()
def orcado_vs_realizado(exercicio: int, divisao: str | None = None) -> dict:
    """Traz o comparativo orçado x realizado mês a mês, e por linha (despesa +
    divisão + equipe), para o exercício informado. Use sempre como base antes de
    comentar sobre gastos de mão de obra — nunca avalie o realizado sem confrontar
    com o orçado."""
    params = {"divisao": divisao} if divisao else None
    return _get(f"/api/orcamento/{exercicio}", params=params)


@mcp.tool()
def linhas_fora_da_meta(
    exercicio: int,
    divisao: str | None = None,
    limite_abaixo: float = 80.0,
    limite_acima: float = 110.0,
) -> dict:
    """Aponta linhas (despesa + divisão + equipe) com consumo do orçamento no ano
    muito acima ou muito abaixo do esperado. Uma linha estourada ao lado de outra
    com bastante sobra é sinal de desequilíbrio a corrigir/equalizar — pode ser
    gasto classificado na linha errada."""
    params = {"divisao": divisao} if divisao else None
    data = _get(f"/api/orcamento/{exercicio}", params=params)
    if not data.get("tem_orcamento"):
        return {"tem_orcamento": False, "acima_do_previsto": [], "abaixo_do_previsto": []}

    acima, abaixo = [], []
    for linha in data["linhas"]:
        tot = linha["total_ano"]
        pct = tot.get("consumo_pct")
        if pct is None:
            continue
        resumo = {
            "despesa": linha["despesa"],
            "divisao": linha["divisao"],
            "equipe": linha["equipe"],
            "orcado": tot["orcado"],
            "realizado": tot["realizado"],
            "saldo": tot["saldo"],
            "consumo_pct": pct,
        }
        if pct > limite_acima:
            acima.append(resumo)
        elif pct < limite_abaixo:
            abaixo.append(resumo)

    acima.sort(key=lambda x: x["consumo_pct"], reverse=True)
    abaixo.sort(key=lambda x: x["consumo_pct"])
    return {"tem_orcamento": True, "acima_do_previsto": acima, "abaixo_do_previsto": abaixo}


@mcp.tool()
def resumo_por_divisao(exercicio: int) -> dict:
    """Soma orçado e realizado por divisão no ano inteiro, para identificar se
    alguma divisão está pagando muito além do previsto e precisa de equalização."""
    data = _get(f"/api/orcamento/{exercicio}")
    if not data.get("tem_orcamento"):
        return {"tem_orcamento": False, "divisoes": []}

    agregados: dict[str, dict] = {}
    for linha in data["linhas"]:
        tot = linha["total_ano"]
        bucket = agregados.setdefault(linha["divisao"], {"orcado": 0.0, "realizado": 0.0})
        bucket["orcado"] += tot["orcado"]
        bucket["realizado"] += tot["realizado"]

    divisoes = []
    for divisao, v in agregados.items():
        orcado, realizado = round(v["orcado"], 2), round(v["realizado"], 2)
        consumo = round(realizado / orcado * 100, 1) if orcado else None
        divisoes.append(
            {
                "divisao": divisao,
                "orcado": orcado,
                "realizado": realizado,
                "saldo": round(orcado - realizado, 2),
                "consumo_pct": consumo,
            }
        )
    divisoes.sort(key=lambda x: (x["consumo_pct"] is None, -(x["consumo_pct"] or 0)))
    return {"tem_orcamento": True, "divisoes": divisoes}


@mcp.tool()
def pessoas_do_mes(exercicio: int, mes: int, divisao: str | None = None) -> dict:
    """Lista, de forma ANONIMIZADA, quem foi alocado no mês: equipe, divisão,
    despesa, valor e se é da equipe (segundo o cadastro). O nome real nunca é
    enviado — cada colaborador vira um pseudônimo estável (o mesmo nome real
    sempre gera o mesmo pseudônimo, mas o processo não é reversível). Use para
    investigar a causa de uma linha ou divisão fora da meta: alguém não
    cadastrado, que saiu, ou vindo de outra área pode explicar o desvio."""
    params: dict = {"mes": mes}
    if divisao:
        params["divisao"] = divisao
    data = _get(f"/api/pessoas-mes/{exercicio}", params=params)
    linhas = []
    for linha in data["linhas"]:
        nova = dict(linha)
        nova["colaborador"] = _anonimizar(linha["colaborador"])
        linhas.append(nova)
    return {"linhas": linhas}


if __name__ == "__main__":
    mcp.run()
