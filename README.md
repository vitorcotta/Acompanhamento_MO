# Acompanhamento MO

Sistema para acompanhar a distribuição de **mão de obra realizada** a partir dos relatórios Excel mensais (equivalente à tabela dinâmica que você usa hoje).

## O que o sistema faz

- Importa os arquivos `.xlsx` da pasta `Excel/` na subida do container
- Permite **upload** de novos arquivos mensais pela interface
- Mostra **total por mês**, **% ADM vs time** e variação em relação ao mês anterior
- Tabela por **Descrição Despesa** (equipe) com valores e variação % mês a mês

### Mapeamento das colunas

| Coluna no Excel | Uso no sistema |
|-----------------|----------------|
| Descrição Despesa | Equipe / linha de rateio |
| Nome | Colaborador |
| Valor realizado rateio | Valor realizado |
| Período contábil | Mês |
| Sistema de origem | `ADM` = rateio administrativo; demais = time |
| Divisão | Filtro na aba **Por divisão** (Comércio, Logística, Holding, etc.) |
| Despesa | Código (ex. R1089) — chave com Divisão para cruzar com **Orçamento.xlsx** |

## Como rodar (Docker)

```bash
docker compose up --build
```

Abra no navegador: **http://localhost:8000**

- **Dashboard**: gráficos e cards mensais (ADM %, total, variação)
- **Por equipe**: visão tipo pivot por linha de despesa
- **Por pessoa**: mesma tabela pivot, agrupada por **Nome** (colaborador)
- **Comparar meses**: escolha 2 ou 3 meses e compare por equipe, pessoa ou divisão
- **Por divisão**: mesmo acompanhamento filtrado pela coluna Divisão
- **Orçado vs realizado**: compara planilha de orçamento (Jan–Dez) com o realizado, pela chave **Despesa + Divisão** (visão anual)
- **Orçado por equipe**: no mês escolhido, orçado vs realizado por **equipe + divisão** (Δ em R$ e %), com filtro de divisão
- **Simular realocação**: altere destino linha a linha sem mudar o banco; exporte Excel só com linhas alteradas (`Nova Despesa`, `Nova Divisão` + **todas** as colunas do realizado mensal original)
- **Upload**: envie o Excel do mês; períodos já existentes são substituídos pelos dados do novo arquivo
- **Arquivos**: histórico do que foi importado

Os dados ficam no volume Docker `mo_data` (banco SQLite + uploads). A pasta `Excel/` do repositório é montada somente leitura para carga inicial; use **Upload** ou copie para o volume se quiser persistir novos arquivos fora do git.

### Reimportar

O botão **Reimportar** reprocessa os realizados e o orçamento em `Excel/` (prioriza `ORÇAMENTO … MÊS A MÊS.xlsx` se houver mais de um arquivo de orçamento), além dos arquivos em `/data/uploads`.

**Orçamento:** após subir pelo Upload, ele fica no volume Docker. Ao reiniciar o container, **não** volta a puxar automaticamente de `Excel/` (só de uploads ou via Reimportar). Para trocar o orçado, use **Upload** ou exclua na aba Arquivos (tipo Orçamento).

## Desenvolvimento local (sem Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATA_DIR=../data
export EXCEL_SEED_DIR=../Excel
mkdir -p ../data/uploads
uvicorn main:app --reload --port 8000
```

Acesse: http://localhost:8000

## Estrutura

```
Excel/                 # arquivos mensais (ex.: MO GESTORES - INFRA - JANEIRO.XLSX)
backend/
  main.py              # API + interface
  importer.py          # leitura Excel
  services.py          # agregações
  static/              # frontend
mcp/
  server.py            # servidor MCP (exposto ao Claude Desktop)
  reveal.py            # CLI local para desanonimizar um pseudônimo
  Dockerfile
docker-compose.yml
Dockerfile
```

## MCP (análise com IA no Claude Desktop)

O serviço `mcp` expõe os dados do app como tools para o Claude Desktop analisar orçado vs. realizado, achar linhas fora da meta e resumos por divisão. Ele sobe junto com o `docker compose up --build` e fica parado (idle) esperando o Claude Desktop entrar via `docker exec -i`.

### Configuração no Claude Desktop

Em `claude_desktop_config.json`, adicione:

```json
"acompanhamento-mo": {
  "command": "docker",
  "args": ["exec", "-i", "acompanhamento_mo-mcp-1", "python", "server.py"]
}
```

Reinicie o Claude Desktop depois de editar o config.

### Tools disponíveis

- `listar_exercicios`
- `orcado_vs_realizado`
- `linhas_fora_da_meta`
- `resumo_por_divisao`
- `pessoas_do_mes`

### Anonimização dos colaboradores

Antes de qualquer nome de colaborador chegar à IA, o `server.py` troca o nome real por um pseudônimo estável (`Colaborador-XXXXXX`), gerado por hash SHA256 de `salt + nome`. O salt é gerado na primeira execução e persiste no volume Docker `mcp_salt`, então o mesmo colaborador sempre vira o mesmo pseudônimo entre sessões — mas a IA nunca vê o nome real nem consegue reverter o hash.

**Para descobrir quem é um `Colaborador-XXXXXX` que apareceu numa análise**, use o script local `reveal.py` (não é uma tool do MCP — só roda manualmente no seu terminal, fora do alcance da IA):

```bash
docker exec -i acompanhamento_mo-mcp-1 python reveal.py Colaborador-9C2710
# ou só o código:
docker exec -i acompanhamento_mo-mcp-1 python reveal.py 9C2710 --exercicio 2026
```
