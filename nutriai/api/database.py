from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Define o caminho para o nosso banco de dados SQLite
# O "///" é necessário para indicar que é um arquivo local
SQLALCHEMY_DATABASE_URL = "sqlite:///./nutriai.db"

# Cria a "engine" do SQLAlchemy, que gerencia a conexão com o banco
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Cria uma fábrica de sessões. Cada sessão é uma "conversa" com o banco de dados.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para nossos modelos. Todas as classes que representam tabelas herdarão dela.
Base = declarative_base()