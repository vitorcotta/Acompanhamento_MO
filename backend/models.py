from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Arquivo(Base):
    __tablename__ = "arquivos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(512), nullable=False)
    hash_conteudo: Mapped[str] = mapped_column(String(64), nullable=False)
    exercicio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meses: Mapped[str] = mapped_column(String(64), default="")
    total_linhas: Mapped[int] = mapped_column(Integer, default=0)
    importado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("nome", name="uq_arquivo_nome"),)


class OrcamentoArquivo(Base):
    __tablename__ = "orcamento_arquivos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    hash_conteudo: Mapped[str] = mapped_column(String(64), nullable=False)
    exercicio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_linhas: Mapped[int] = mapped_column(Integer, default=0)
    importado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Orcamento(Base):
    __tablename__ = "orcamento"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    arquivo_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    exercicio: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    despesa: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    equipe: Mapped[str] = mapped_column(String(256), nullable=False)
    divisao: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mes: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    valor: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("exercicio", "despesa", "divisao", "mes", name="uq_orcamento_chave"),
    )


class Lancamento(Base):
    __tablename__ = "lancamentos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    arquivo_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    exercicio: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    mes: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    despesa: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    equipe: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    divisao: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    colaborador: Mapped[str] = mapped_column(String(256), nullable=False)
    valor: Mapped[float] = mapped_column(Float, nullable=False)
    origem: Mapped[str] = mapped_column(String(32), nullable=False)
    is_adm: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
