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
- **Por divisão**: mesmo acompanhamento filtrado pela coluna Divisão
- **Orçado vs realizado**: compara planilha `Orçamento.xlsx` (Jan–Dez) com o realizado, pela chave **Despesa + Divisão**
- **Upload**: envie o Excel do mês; períodos já existentes são substituídos pelos dados do novo arquivo
- **Arquivos**: histórico do que foi importado

Os dados ficam no volume Docker `mo_data` (banco SQLite + uploads). A pasta `Excel/` do repositório é montada somente leitura para carga inicial; use **Upload** ou copie para o volume se quiser persistir novos arquivos fora do git.

### Reimportar

O botão **Reimportar** reprocessa tudo em `Excel/` e em `/data/uploads` (útil após adicionar arquivos na pasta sem subir de novo).

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
docker-compose.yml
Dockerfile
```
