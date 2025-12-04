import os
import json
import re
import random
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from thefuzz import process as fuzz_process

from . import models, schemas, pdf_generator
from .database import SessionLocal, engine
import google.generativeai as genai

# --- Configuração ---
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: raise ValueError("Chave de API GOOGLE_API_KEY não encontrada.")
    genai.configure(api_key=api_key)
except (ValueError, TypeError) as e: print(f"ERRO DE CONFIGURAÇÃO DO GEMINI: {e}")

models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="NutriAI API", description="API para planejamento de dietas.", version="1.0.0")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# --- ENDPOINT ---
@app.post("/planejar-dieta/", response_class=FileResponse)
def planejar_dieta(request: schemas.UserRequestSchema, db: Session = Depends(get_db)):
    
    # 1. CÁLCULO CALÓRICO
    if request.sexo == 'masculino':
        meta_calorica = (10 * request.peso_kg) + (6.25 * request.altura_cm) - (5 * request.idade) + 5
    else:
        meta_calorica = (10 * request.peso_kg) + (6.25 * request.altura_cm) - (5 * request.idade) - 161
    fatores = {"sedentario": 1.2, "leve": 1.375, "moderado": 1.55, "ativo": 1.725}
    meta_calorica *= fatores.get(request.nivel_atividade, 1.55)
    if request.objetivo == 'perder_peso': meta_calorica -= 500
    elif request.objetivo == 'ganhar_massa': meta_calorica += 500

    # 2. BUSCAR RECEITAS
    restricao_map = {
        'vegano': models.Receita.is_vegan, 'vegetariano': models.Receita.is_vegetarian, 
        'sem_gluten': models.Receita.is_gluten_free, 'sem_lactose': models.Receita.is_lactose_free, 
        'sem_oleaginosas': models.Receita.is_nut_free, 'sem_frutos_do_mar': models.Receita.is_seafood_free, 
        'sem_ovo': models.Receita.is_egg_free, 'sem_soja': models.Receita.is_soy_free
    }
    
    query = db.query(models.Receita).filter(models.Receita.nutrientes_calculados == True)
    
    if request.restricoes:
        for r in request.restricoes:
            col = restricao_map.get(r.lower())
            if col is not None: query = query.filter(col == True)
    
    receitas_db = query.all()
    
    mapa_titulos = {}
    titulos_prompt = []
    
    for r in receitas_db:
        if not r.titulo: continue
        t_limpo = r.titulo.strip()
        t_norm = t_limpo.lower().strip()
        
        if t_norm not in mapa_titulos:
            mapa_titulos[t_norm] = r
            macros = ""
            if r.informacoes_nutricionais and isinstance(r.informacoes_nutricionais, dict):
                k = r.informacoes_nutricionais.get('calorias', 0)
                p = r.informacoes_nutricionais.get('proteina', 0)
                if k > 50: macros = f" (Total Receita: {k:.0f} kcal, {p:.0f}g P)"
            titulos_prompt.append(f"{t_limpo}{macros}")

    amostra = random.sample(titulos_prompt, min(len(titulos_prompt), 600))
    lista_formatada = "\n- ".join(amostra) if amostra else "Nenhuma receita encontrada."

    # 3. PROMPT REFINADO (HIERARQUIA VISUAL H2/H3)
    prompt_para_ia = f"""
    Aja como uma nutricionista. Crie um plano SEMANAL (7 dias) para:
    Perfil: {request.sexo}, {request.idade} anos, {request.objetivo}.
    Meta: {meta_calorica:.0f} kcal.
    
    ESTRUTURA OBRIGATÓRIA (SEMANAL):
    - Segunda a Sexta:
        - Almoço e Jantar: 3 Opções SAUDÁVEIS (Opções 1 e 2 baseadas na lista abaixo, Opção 3 sugestão leve).
        - Café/Lanches/Ceia: 3 Opções SAUDÁVEIS variadas.
    - Sábado e Domingo:
        - Permita 1 "Opção Livre" no Almoço OU Jantar.
        - As outras refeições seguem o padrão saudável.

    REGRAS DE FORMATO (CRÍTICO PARA PDF):
    1. Use a estrutura de Markdown abaixo EXATAMENTE para hierarquia visual:
       ## Segunda-Feira
       ### Café da Manhã
       - Opção 1: Nome do Prato (Descrição da porção) + Acompanhamentos.
       - Opção 2: Nome do Prato (Descrição da porção) + Acompanhamentos.
       ### Lanche da Manhã
       - Opção 1: ...
    2. NÃO pule linha dentro da opção. Mantenha tudo no mesmo parágrafo.
    3. NÃO escreva "(Receita)" ou "(Prático)" no início da linha. Comece direto com "Opção X:".

    REGRAS PARA RECEITAS DO BANCO:
    1. Para as opções baseadas na lista abaixo, use o NOME EXATO.
    2. Use porções humanas ("Metade da receita", "1 prato raso").

    LISTA DE RECEITAS DISPONÍVEIS:
    - {lista_formatada}

    FORMATO JSON (ÚNICO):
    {{
      "plano_texto": "## Segunda-Feira\\n### Café da Manhã\\n- Opção 1: ...",
      "receitas_sugeridas": {{
          "Nome Exato da Receita 1": "Segunda - Almoço",
          "Nome Exato da Receita 2": "Terça - Jantar"
      }}
    }}
    """

    # 4. CHAMADA IA
    try:
        model = genai.GenerativeModel('models/gemini-flash-latest')
        response = model.generate_content(prompt_para_ia, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        
        json_text = response.text.strip()
        if json_text.startswith("```json"): json_text = json_text[7:]
        if json_text.endswith("```"): json_text = json_text[:-3]
        response_json = json.loads(json_text.strip())

    except Exception as e:
        print(f"ERRO IA: {e}")
        raise HTTPException(status_code=500, detail="Erro ao gerar plano com IA.")

    # 5. FILTRAGEM
    sugestoes = response_json.get("receitas_sugeridas", {})
    mapa_encontradas = {} 

    if isinstance(sugestoes, dict):
        titulos_norm_db = list(mapa_titulos.keys())
        for t_ia, dia in sugestoes.items():
            t_ia_limpo = t_ia.lower().strip().split('(')[0].strip()
            
            match = fuzz_process.extractOne(t_ia_limpo, titulos_norm_db)
            if match and match[1] >= 90:
                r_db = mapa_titulos.get(match[0])
                if r_db:
                    if r_db.id not in mapa_encontradas:
                         mapa_encontradas[r_db.id] = {"receita": r_db, "dia": dia}
                    else:
                        mapa_encontradas[r_db.id]["dia"] += f", {dia}"

    # 6. FORMATAR PARA PDF
    receitas_pdf = []
    for rid, data in mapa_encontradas.items():
        rec = data["receita"]
        
        nutri_str = "Análise em andamento"
        info = getattr(rec, 'informacoes_nutricionais', {})
        if info and isinstance(info, dict) and info.get('calorias', 0) > 0:
             nutri_str = f"🔥 {info.get('calorias', 0):.0f} kcal | 🥩 P: {info.get('proteina', 0):.0f}g | 🍞 C: {info.get('carboidratos', 0):.0f}g | 🥑 G: {info.get('lipideos', 0):.0f}g"

        receitas_pdf.append({
            "titulo": getattr(rec, 'titulo', "Sem Título"),
            "modo_preparo": getattr(rec, 'modo_preparo', ""),
            "ingredientes": getattr(rec, 'ingredientes', []),
            "dia_sugerido": data["dia"],
            "nutri_info": nutri_str
        })

    # 7. GERAR PDF
    try:
        plano_texto_md = response_json.get("plano_texto", "Erro no plano.")
        pdf_path = pdf_generator.criar_pdf_plano_excelente(
            plano_texto_md=plano_texto_md,
            receitas_detalhadas=receitas_pdf,
            user_data=request,
            meta_calorica=meta_calorica
        )
        return FileResponse(pdf_path, media_type='application/pdf', filename=f"Plano_{request.tipo_plano}.pdf", background=BackgroundTask(os.remove, pdf_path))
    except Exception as e:
        print(f"ERRO PDF: {e}")
        raise HTTPException(status_code=500, detail="Erro ao gerar PDF.")

@app.get("/health")
def health(): return {"status": "ok"}