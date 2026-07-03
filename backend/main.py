import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import UPLOAD_DIR, Base, clear_all_data, engine, get_db, migrate_schema
from budget_importer import (
    _nome_normalizado,
    delete_orcamento_arquivo,
    import_orcamento_directory,
    import_orcamento_file,
    is_orcamento_file,
)
from importer import import_directory, import_file
from models import Arquivo, OrcamentoArquivo
from simulation import exportar_ajustes_xlsx, list_destinos, list_lancamentos
from services import (
    colaboradores,
    comparativo_equipe_mes,
    comparativo_orcamento,
    comparar_meses,
    list_arquivos,
    list_divisoes,
    list_exercicios,
    list_meses,
    pivot_colaboradores,
    pivot_equipes,
    resumo_divisoes_mensal,
    resumo_mensal,
)

EXCEL_SEED_DIR = Path(os.environ.get("EXCEL_SEED_DIR", "/seed/Excel"))
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    if migrate_schema():
        clear_all_data()
    from database import SessionLocal

    db = SessionLocal()
    try:
        import_directory(db, EXCEL_SEED_DIR)
        import_directory(db, UPLOAD_DIR)
        # Orçamento: só uploads persistidos (não reimporta Excel/ a cada restart)
        import_orcamento_directory(db, UPLOAD_DIR)
    finally:
        db.close()
    yield


app = FastAPI(title="Acompanhamento MO", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/exercicios")
def api_exercicios(db: Session = Depends(get_db)):
    return {"exercicios": list_exercicios(db)}


@app.get("/api/arquivos")
def api_arquivos(db: Session = Depends(get_db)):
    return {"arquivos": list_arquivos(db)}


@app.get("/api/divisoes/{exercicio}")
def api_divisoes(exercicio: int, db: Session = Depends(get_db)):
    return {"divisoes": list_divisoes(db, exercicio)}


@app.get("/api/resumo/{exercicio}")
def api_resumo(
    exercicio: int, divisao: str | None = None, db: Session = Depends(get_db)
):
    return {"resumo": resumo_mensal(db, exercicio, divisao)}


@app.get("/api/divisoes-mensal/{exercicio}")
def api_divisoes_mensal(exercicio: int, db: Session = Depends(get_db)):
    return resumo_divisoes_mensal(db, exercicio)


@app.get("/api/orcamento/{exercicio}")
def api_orcamento(
    exercicio: int, divisao: str | None = None, db: Session = Depends(get_db)
):
    return comparativo_orcamento(db, exercicio, divisao)


@app.get("/api/orcamento-equipe/{exercicio}")
def api_orcamento_equipe(
    exercicio: int,
    mes: int = Query(..., ge=1, le=12),
    divisao: str | None = None,
    db: Session = Depends(get_db),
):
    return comparativo_equipe_mes(db, exercicio, mes, divisao)


@app.get("/api/meses/{exercicio}")
def api_meses(exercicio: int, db: Session = Depends(get_db)):
    return {"meses": list_meses(db, exercicio)}


@app.get("/api/simulacao/{exercicio}/lancamentos")
def api_simulacao_lancamentos(
    exercicio: int,
    mes: int = Query(..., ge=1, le=12),
    divisao: str | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
):
    linhas = list_lancamentos(db, exercicio, mes, divisao=divisao, busca=busca)
    return {"mes": mes, "linhas": linhas, "total": len(linhas)}


@app.get("/api/simulacao/{exercicio}/destinos")
def api_simulacao_destinos(
    exercicio: int,
    mes: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    return {"destinos": list_destinos(db, exercicio, mes)}


@app.post("/api/simulacao/{exercicio}/exportar")
def api_simulacao_exportar(
    exercicio: int,
    mes: int = Query(..., ge=1, le=12),
    body: dict = Body(...),
    db: Session = Depends(get_db),
):
    ajustes = body.get("ajustes")
    if not isinstance(ajustes, list):
        raise HTTPException(400, "Campo 'ajustes' deve ser uma lista.")
    try:
        conteudo, nome = exportar_ajustes_xlsx(db, exercicio, mes, ajustes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@app.get("/api/comparar/{exercicio}")
def api_comparar(
    exercicio: int,
    meses: str = Query(..., description="Meses separados por vírgula, ex: 1,2 ou 3,4,5"),
    dimensao: str = Query("equipe", pattern="^(equipe|pessoa|divisao)$"),
    db: Session = Depends(get_db),
):
    try:
        mes_list = [int(m.strip()) for m in meses.split(",") if m.strip()]
    except ValueError as exc:
        raise HTTPException(400, "Meses inválidos") from exc
    try:
        return comparar_meses(db, exercicio, mes_list, dimensao)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/pivot/{exercicio}")
def api_pivot(
    exercicio: int, divisao: str | None = None, db: Session = Depends(get_db)
):
    return pivot_equipes(db, exercicio, divisao)


@app.get("/api/pivot-pessoas/{exercicio}")
def api_pivot_pessoas(
    exercicio: int, equipe: str | None = None, db: Session = Depends(get_db)
):
    return pivot_colaboradores(db, exercicio, equipe)


@app.get("/api/colaboradores/{exercicio}")
def api_colaboradores(
    exercicio: int, mes: int | None = None, db: Session = Depends(get_db)
):
    return {"colaboradores": colaboradores(db, exercicio, mes)}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Envie um arquivo Excel (.xlsx)")

    nome = Path(file.filename).name
    dest = UPLOAD_DIR / nome
    content = await file.read()
    dest.write_bytes(content)

    try:
        if is_orcamento_file(Path(nome)) or is_orcamento_file(dest):
            arquivo = import_orcamento_file(db, dest, force=True)
            return {
                "ok": True,
                "tipo": "orcamento",
                "arquivo": {
                    "nome": arquivo.nome,
                    "exercicio": arquivo.exercicio,
                    "total_linhas": arquivo.total_linhas,
                },
            }
        arquivo = import_file(db, dest)
        return {
            "ok": True,
            "tipo": "realizado",
            "arquivo": {
                "nome": arquivo.nome,
                "exercicio": arquivo.exercicio,
                "meses": arquivo.meses,
                "total_linhas": arquivo.total_linhas,
            },
        }
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f"Erro ao importar: {exc}") from exc


@app.post("/api/reimport")
def api_reimport(db: Session = Depends(get_db)):
    from models import Lancamento

    from models import Orcamento, OrcamentoArquivo

    db.query(Lancamento).delete()
    db.query(Arquivo).delete()
    db.query(Orcamento).delete()
    db.query(OrcamentoArquivo).delete()
    db.commit()
    import_directory(db, EXCEL_SEED_DIR)
    import_directory(db, UPLOAD_DIR)
    import_orcamento_directory(db, EXCEL_SEED_DIR)
    import_orcamento_directory(db, UPLOAD_DIR)
    return {"ok": True, "arquivos": list_arquivos(db)}


@app.delete("/api/arquivos/{arquivo_id}")
def api_delete_arquivo(
    arquivo_id: int,
    tipo: str = Query("realizado", pattern="^(realizado|orcamento)$"),
    db: Session = Depends(get_db),
):
    from models import Lancamento

    if tipo == "orcamento":
        arquivo = db.get(OrcamentoArquivo, arquivo_id)
        if not arquivo:
            raise HTTPException(404, "Arquivo de orçamento não encontrado")
        nome = arquivo.nome
        delete_orcamento_arquivo(db, arquivo_id)
        alvo = _nome_normalizado(Path(nome))
        for path in UPLOAD_DIR.glob("*.xlsx"):
            if is_orcamento_file(path) and _nome_normalizado(path) == alvo:
                path.unlink(missing_ok=True)
        for path in UPLOAD_DIR.glob("*.XLSX"):
            if is_orcamento_file(path) and _nome_normalizado(path) == alvo:
                path.unlink(missing_ok=True)
        return {"ok": True, "tipo": "orcamento"}

    arquivo = db.get(Arquivo, arquivo_id)
    if not arquivo:
        raise HTTPException(404, "Arquivo não encontrado")
    db.query(Lancamento).filter(Lancamento.arquivo_id == arquivo_id).delete()
    db.delete(arquivo)
    db.commit()

    upload_path = UPLOAD_DIR / arquivo.nome
    if upload_path.is_file():
        upload_path.unlink()

    return {"ok": True, "tipo": "realizado"}
