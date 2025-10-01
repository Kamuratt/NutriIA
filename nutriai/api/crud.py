# api/crud.py
from sqlalchemy.orm import Session
from sqlalchemy import func # Importe a função 'func'
from . import models
from typing import List

def get_receitas(db: Session, skip: int = 0, limit: int = 10):
    """Busca uma lista de receitas do banco de dados."""
    return db.query(models.Receita).offset(skip).limit(limit).all()

def get_receitas_nutricionais_sample(db: Session, limit: int = 20):
    """Busca uma amostra aleatória de receitas que já têm nutrientes calculados."""
    return db.query(models.Receita).join(models.InformacoesNutricionais).order_by(func.random()).limit(limit).all()

def get_receitas_by_ids(db: Session, ids: List[int]):
    """Busca um conjunto de receitas a partir de uma lista de IDs."""
    if not ids:
        return []
    return db.query(models.Receita).filter(models.Receita.id.in_(ids)).all()