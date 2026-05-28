import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import UPLOAD_DIR, Base, clear_all_data, engine, get_db, migrate_schema
from budget_importer import import_orcamento_directory, import_orcamento_file, is_orcamento_file
from importer import import_directory, import_file
from models import Arquivo
from services import (
    colaboradores,
    comparativo_orcamento,
    list_arquivos,
    list_divisoes,
    list_exercicios,
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
        import_orcamento_directory(db, EXCEL_SEED_DIR)
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


@app.get("/api/pivot/{exercicio}")
def api_pivot(
    exercicio: int, divisao: str | None = None, db: Session = Depends(get_db)
):
    return pivot_equipes(db, exercicio, divisao)


@app.get("/api/colaboradores/{exercicio}")
def api_colaboradores(
    exercicio: int, mes: int | None = None, db: Session = Depends(get_db)
):
    return {"colaboradores": colaboradores(db, exercicio, mes)}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Envie um arquivo Excel (.xlsx)")

    dest = UPLOAD_DIR / Path(file.filename).name
    content = await file.read()
    dest.write_bytes(content)

    try:
        if is_orcamento_file(dest):
            arquivo = import_orcamento_file(db, dest)
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
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc

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
def api_delete_arquivo(arquivo_id: int, db: Session = Depends(get_db)):
    from models import Lancamento

    arquivo = db.get(Arquivo, arquivo_id)
    if not arquivo:
        raise HTTPException(404, "Arquivo não encontrado")
    db.query(Lancamento).filter(Lancamento.arquivo_id == arquivo_id).delete()
    db.delete(arquivo)
    db.commit()

    upload_path = UPLOAD_DIR / arquivo.nome
    if upload_path.is_file():
        upload_path.unlink()

    return {"ok": True}
