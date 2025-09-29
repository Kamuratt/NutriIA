# api/crud.py
from sqlalchemy.orm import Session
from sqlalchemy import func # Importe a função 'func'
from . import models

def get_receitas(db: Session, skip: int = 0, limit: int = 10):
    """Busca uma lista de receitas do banco de dados."""
    return db.query(models.Receita).offset(skip).limit(limit).all()

# --- ADICIONE A FUNÇÃO ABAIXO ---

def get_receitas_nutricionais_sample(db: Session, limit: int = 20):
    """Busca uma amostra aleatória de receitas que já têm nutrientes calculados."""
    return db.query(models.Receita).join(models.InformacoesNutricionais).order_by(func.random()).limit(limit).all()