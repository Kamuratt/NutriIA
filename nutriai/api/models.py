# api/models.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey, REAL, Boolean
from sqlalchemy.orm import relationship
from .database import Base

# Espelho da tabela 'receitas'
class Receita(Base):
    __tablename__ = "receitas"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, unique=True, index=True)
    url = Column(String, unique=True)
    modo_preparo = Column(Text)
    processado_pela_llm = Column(Boolean, default=False)
    nutrientes_calculados = Column(Boolean, default=False)
    
    ingredientes = relationship("Ingrediente", back_populates="receita")
    
    # --- ADICIONE A RELAÇÃO ABAIXO ---
    info_nutricional = relationship("InformacoesNutricionais", back_populates="receita", uselist=False)

# Espelho da tabela 'ingredientes'
class Ingrediente(Base):
    __tablename__ = "ingredientes"
    id = Column(Integer, primary_key=True, index=True)
    descricao = Column(String)
    receita_id = Column(Integer, ForeignKey("receitas.id"))
    receita = relationship("Receita", back_populates="ingredientes")

# --- ADICIONE A NOVA CLASSE ABAIXO ---

# Espelho da tabela 'informacoes_nutricionais'
class InformacoesNutricionais(Base):
    __tablename__ = "informacoes_nutricionais"
    id = Column(Integer, primary_key=True, index=True)
    receita_id = Column(Integer, ForeignKey("receitas.id"), unique=True)
    calorias_total = Column(REAL)
    proteina_total = Column(REAL)
    lipideos_total = Column(REAL)
    carboidratos_total = Column(REAL)
    fibras_total = Column(REAL)

    receita = relationship("Receita", back_populates="info_nutricional")