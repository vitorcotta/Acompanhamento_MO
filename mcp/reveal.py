"""Resolve um pseudônimo ("Colaborador-XXXXXX") de volta ao nome real.

Uso local apenas — roda fora de qualquer conversa com IA. NUNCA exponha isso
como tool do MCP (o server.py não importa nada daqui), senão o Claude Desktop
passa a conseguir desanonimizar sozinho, o que anula o propósito do salt.

Uso:
    docker exec -i acompanhamento_mo-mcp-1 python reveal.py Colaborador-9C2710
    docker exec -i acompanhamento_mo-mcp-1 python reveal.py 9C2710 --exercicio 2026
"""

import argparse
import sys

from server import _anonimizar, _get


def _nomes_do_exercicio(exercicio: int) -> set[str]:
    data = _get(f"/api/pivot-pessoas/{exercicio}")
    return set(data.get("colaboradores", []))


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve um pseudônimo para o nome real.")
    parser.add_argument("pseudonimo", help='ex.: "Colaborador-9C2710" ou só "9C2710"')
    parser.add_argument("--exercicio", type=int, help="restringe a busca a um exercício")
    args = parser.parse_args()

    alvo = args.pseudonimo
    if not alvo.lower().startswith("colaborador-"):
        alvo = f"Colaborador-{alvo.upper()}"
    else:
        alvo = f"Colaborador-{alvo.split('-', 1)[1].upper()}"

    exercicios = [args.exercicio] if args.exercicio else _get("/api/exercicios")["exercicios"]

    for exercicio in exercicios:
        for nome in _nomes_do_exercicio(exercicio):
            # pessoas_do_mes anonimiza o nome já com espaços normalizados
            # (" ".join(nome.split())); testamos as duas formas pra não
            # perder quem tem variação de espaçamento no Excel de origem.
            candidatos = {nome, " ".join(nome.split())}
            if any(_anonimizar(c) == alvo for c in candidatos):
                print(f"{alvo} = {nome}  (exercício {exercicio})")
                return

    print(f"Não encontrei nenhum colaborador correspondente a {alvo}.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
