# api/models.py
from sqlalchemy import Column, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from .database import Base

class Receita(Base):
    __tablename__ = "receitas"

    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, unique=True, index=True)
    url = Column(String, unique=True)
    ingredientes_brutos = Column(JSONB) # Campo original
    modo_preparo = Column(Text)
    
    # Colunas que nossos scripts preenchem
    processado_pela_llm = Column(Boolean, default=False)
    ingredientes = Column(JSONB) # O JSON estruturado
    
    nutrientes_calculados = Column(Boolean, default=False)
    informacoes_nutricionais = Column(JSONB) # O JSON de nutrientes
    
    revisado = Column(Boolean, default=False)
    
    # --- [INÍCIO DA ATUALIZAÇÃO] ---
    # Colunas preenchidas pelo script revisar_receitas_processadas.py
    is_vegan = Column(Boolean, default=False)
    is_vegetarian = Column(Boolean, default=False)
    is_gluten_free = Column(Boolean, default=False)
    is_lactose_free = Column(Boolean, default=False)
    is_nut_free = Column(Boolean, default=False)
    is_seafood_free = Column(Boolean, default=False)
    is_egg_free = Column(Boolean, default=False)
    is_soy_free = Column(Boolean, default=False)
    # --- [FIM DA ATUALIZAÇÃO] ---