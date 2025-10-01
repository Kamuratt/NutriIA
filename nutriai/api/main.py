# api/main.py
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import google.generativeai as genai
import os
from fastapi.middleware.cors import CORSMiddleware
from . import crud, models, schemas
from .database import SessionLocal, engine
import calculadora_metabolica
from dotenv import load_dotenv
import json
import re

load_dotenv()

# Configura a API do Gemini
try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
except Exception as e:
    print(f"ERRO ao configurar a API do Gemini: {e}")

models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="NutriAI API",
    description="API para fornecer dados de receitas e planejamento de dietas inteligentes.",
    version="1.0.0",
)

# Configuração do CORS
origins = [
    "http://localhost",
    "http://localhost:8501",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- NOVA FUNÇÃO AUXILIAR PARA O PROMPT ---
def gerar_texto_explicativo_restricoes(restricoes: List[str]) -> str:
    """Gera um texto detalhado explicando as restrições para a IA."""
    if not restricoes:
        return "Nenhuma."
    
    explicacoes = []
    if "vegano" in restricoes:
        explicacoes.append("VEGANO: Excluir completamente qualquer receita que contenha carne (bovina, frango, peixe), laticínios (leite, queijo, manteiga, iogurte), ovos e mel.")
    if "vegetariano" in restricoes:
        explicacoes.append("VEGETARIANO: Excluir receitas que contenham qualquer tipo de carne (bovina, frango, peixe). Ovos e laticínios são permitidos.")
    if "sem_gluten" in restricoes:
        explicacoes.append("SEM GLÚTEN: Excluir receitas com trigo, centeio ou cevada. Ficar atento a ingredientes como farinha de trigo, pão, macarrão e massas em geral.")
    if "sem_lactose" in restricoes:
        explicacoes.append("SEM LACTOSE: Excluir receitas com laticínios como leite, queijo, iogurte, creme de leite e manteiga.")
    
    return "\n- ".join(explicacoes)

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

@app.post("/planejar-dieta/", response_model=schemas.DietPlanResponseSchema)
def planejar_dieta(user_data: schemas.UserRequestSchema, db: Session = Depends(get_db)):
    try:
        tmb = calculadora_metabolica.calcular_tmb(
            user_data.peso_kg, user_data.altura_cm, user_data.idade, user_data.sexo
        )
        meta_calorica = calculadora_metabolica.calcular_meta_calorica(
            tmb, user_data.nivel_atividade, user_data.objetivo
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    receitas_disponiveis = crud.get_receitas_nutricionais_sample(db, limit=50)
    if not receitas_disponiveis:
        raise HTTPException(status_code=404, detail="Não há receitas com dados nutricionais suficientes no banco.")

    texto_receitas = ""
    for receita in receitas_disponiveis:
        if receita.info_nutricional:
            info = receita.info_nutricional
            texto_receitas += f"- ID: {receita.id}, Título: {receita.titulo}, Calorias: {info.calorias_total:.0f}, Proteínas: {info.proteina_total:.0f}g\n"
    
    # Gera o texto detalhado das restrições usando a nova função
    texto_explicativo_restricoes = gerar_texto_explicativo_restricoes(user_data.restricoes)

    # --- PROMPT FINAL E MAIS COMPLETO ---
    prompt = f"""
    Você é um nutricionista digital e chef de cozinha, especialista em culinária brasileira. Sua tarefa é criar um plano de refeições detalhado para um dia inteiro e retornar suas escolhas em um formato JSON.

    **DADOS DO USUÁRIO:**
    - Objetivo: {user_data.objetivo.replace('_', ' ')}
    - Meta Calórica Diária: {meta_calorica:.0f} kcal
    - **RESTRIÇÕES ALIMENTARES (Regra Crítica):**
    - {texto_explicativo_restricoes}

    **RECEITAS DISPONÍVEIS (para sua referência interna):**
    {texto_receitas}

    **INSTRUÇÕES OBRIGATÓRIAS:**
    1.  **FILTRAGEM:** Analise os títulos das receitas. Selecione APENAS receitas que sejam estritamente compatíveis com as restrições alimentares do usuário. Se as restrições forem "Nenhuma", você pode usar qualquer receita. Se nenhuma receita for compatível, retorne uma lista de IDs vazia.
    2.  **ESTRUTURA DO PLANO:** Crie um plano de refeições para o dia todo, com 5 refeições: Café da Manhã, Lanche da Manhã, Almoço, Lanche da Tarde e Jantar.
    3.  **SELEÇÃO INTELIGENTE:** Escolha de 2 a 4 receitas da lista filtrada que, combinadas, ajudem o usuário a atingir a meta calórica. Você pode sugerir porções menores (ex: "metade da porção") ou repetir receitas para os lanches, se fizer sentido. Seja criativo para montar o plano.
    4.  **TEXTO DO PLANO:** Crie um texto amigável (em Markdown) com uma tabela e justificativa para o plano. A tabela deve conter as 5 refeições. **NUNCA, EM NENHUMA CIRCUNSTÂNCIA, mencione o 'ID' da receita no texto final (ex: NÃO escreva 'Almôndegas (ID 56)'). O ID é apenas para seu uso interno.**
    5.  **FORMATO DA RESPOSTA:** Retorne APENAS um objeto JSON válido, envolto em ```json ... ```. A estrutura do JSON deve ser:
    {{
      "plano_texto": "...",
      "ids_receitas_selecionadas": [ID_DA_RECEITA_1, ID_DA_RECEITA_2, ...]
    }}
    """

    try:
        model = genai.GenerativeModel('models/gemini-flash-latest')
        response = model.generate_content(prompt)
        
        match = re.search(r"```json\s*(\{.*\})\s*```", response.text, re.DOTALL)
        json_text = ""
        if match:
            json_text = match.group(1)
        else:
            match = re.search(r"(\{.*\})", response.text, re.DOTALL)
            if match:
                json_text = match.group(1)

        if not json_text:
            raise ValueError(f"A IA não retornou um JSON válido. Resposta recebida: {response.text}")

        ai_response_json = json.loads(json_text)
        
        plano_texto_ai = ai_response_json.get("plano_texto", "")
        ids_selecionados = ai_response_json.get("ids_receitas_selecionadas", [])
        
        if not ids_selecionados and user_data.restricoes:
             plano_texto_ai = f"Poxa, com base nas receitas disponíveis, não consegui montar um plano que atendesse às suas restrições alimentares ({', '.join(user_data.restricoes).replace('_', ' ')}). Tente novamente com menos restrições ou mais tarde, quando tivermos mais receitas!"

        receitas_detalhadas = crud.get_receitas_by_ids(db, ids=ids_selecionados)
        
        return schemas.DietPlanResponseSchema(
            plano_texto=plano_texto_ai,
            meta_calorica_calculada=round(meta_calorica, 2),
            receitas_detalhadas=receitas_detalhadas
        )
    except (ValueError, json.JSONDecodeError, Exception) as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar a resposta da IA: {e}")