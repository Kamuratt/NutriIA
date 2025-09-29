# api/main.py
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import google.generativeai as genai
import os

from . import crud, models, schemas
from .database import SessionLocal, engine
# Importa o nosso módulo de cálculo que criamos!
import calculadora_metabolica

# Configura a API do Gemini
try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
except Exception as e:
    print(f"ERRO ao configurar a API do Gemini: {e}")

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/receitas/", response_model=List[schemas.ReceitaSchema])
def read_receitas(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    receitas = crud.get_receitas(db, skip=skip, limit=limit)
    return receitas

# --- NOSSO NOVO ENDPOINT INTELIGENTE ---

@app.post("/planejar-dieta/", response_model=schemas.DietPlanResponseSchema)
def planejar_dieta(user_data: schemas.UserRequestSchema, db: Session = Depends(get_db)):
    """
    Recebe dados do usuário, calcula a meta calórica e usa a IA para gerar um plano de dieta.
    """
    try:
        # 1. Usa nosso módulo para calcular a meta calórica
        tmb = calculadora_metabolica.calcular_tmb(
            user_data.peso_kg, user_data.altura_cm, user_data.idade, user_data.sexo
        )
        meta_calorica = calculadora_metabolica.calcular_meta_calorica(
            tmb, user_data.nivel_atividade, user_data.objetivo
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 2. Busca uma amostra de receitas do banco para dar contexto à IA
    receitas_disponiveis = crud.get_receitas_nutricionais_sample(db, limit=30)
    if not receitas_disponiveis:
        raise HTTPException(status_code=404, detail="Não há receitas com dados nutricionais suficientes no banco.")

    # 3. Monta o prompt para a IA
    texto_receitas = ""
    for receita in receitas_disponiveis:
        info = receita.info_nutricional
        texto_receitas += f"- Título: {receita.titulo}, Calorias: {info.calorias_total:.0f}, Proteínas: {info.proteina_total:.0f}g\n"
    
    prompt = f"""
    Você é um assistente de nutrição. Sua tarefa é criar um plano de refeições simples para um dia (café da manhã, almoço, jantar)
    baseado nas informações do usuário e em uma lista de receitas disponíveis.

    **Dados do Usuário:**
    - Objetivo: {user_data.objetivo}
    - Meta Calórica Diária: {meta_calorica:.0f} kcal

    **Receitas Disponíveis (com seus nutrientes):**
    {texto_receitas}

    **Instruções:**
    1. Selecione de 2 a 3 receitas da lista que ajudem o usuário a atingir sua meta calórica.
    2. Organize as receitas selecionadas em um plano de refeições para café da manhã, almoço e jantar.
    3. Escreva uma breve justificativa para suas escolhas.
    4. Retorne o plano em um texto único e amigável.
    """

    # 4. Chama a IA para gerar o plano
    try:
        model = genai.GenerativeModel('models/gemini-flash-latest')
        response = model.generate_content(prompt)
        
        return schemas.DietPlanResponseSchema(
            plano_texto=response.text,
            meta_calorica_calculada=round(meta_calorica, 2)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar o plano com a IA: {e}")