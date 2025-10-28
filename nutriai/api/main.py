import os
import json
import re
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from . import models, schemas, pdf_generator
from .database import SessionLocal, engine
import google.generativeai as genai

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: raise ValueError("Chave de API GOOGLE_API_KEY não encontrada.")
    genai.configure(api_key=api_key)
except (ValueError, TypeError) as e:
    print(f"ERRO DE CONFIGURAÇÃO DO GEMINI: {e}")

models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="NutriAI API", description="API para planejamento de dietas.", version="1.0.0")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/planejar-dieta/", response_class=FileResponse)
def planejar_dieta(request: schemas.UserRequestSchema, db: Session = Depends(get_db)):
    """Gera um plano de dieta completo (semanal ou mensal) e retorna como um PDF."""

    if request.sexo == 'masculino':
        meta_calorica = (10 * request.peso_kg) + (6.25 * request.altura_cm) - (5 * request.idade) + 5
    else:
        meta_calorica = (10 * request.peso_kg) + (6.25 * request.altura_cm) - (5 * request.idade) - 161
    fatores_atividade = {"sedentario": 1.2, "leve": 1.375, "moderado": 1.55, "ativo": 1.725}
    meta_calorica *= fatores_atividade.get(request.nivel_atividade, 1.55)
    if request.objetivo == 'perder_peso': meta_calorica -= 500
    elif request.objetivo == 'ganhar_massa': meta_calorica += 500

    restricao_map = {
        'vegano': models.Receita.is_vegan, 'vegetariano': models.Receita.is_vegetarian,
        'sem_gluten': models.Receita.is_gluten_free, 'sem_lactose': models.Receita.is_lactose_free,
        'sem_oleaginosas': models.Receita.is_nut_free, 'sem_frutos_do_mar': models.Receita.is_seafood_free,
        'sem_ovo': models.Receita.is_egg_free, 'sem_soja': models.Receita.is_soy_free
    }
    query = db.query(models.Receita).filter(models.Receita.revisado == True)
    if request.restricoes:
        for restricao in request.restricoes:
            coluna_filtro = restricao_map.get(restricao.lower())
            if coluna_filtro is not None:
                query = query.filter(coluna_filtro == True)
    receitas_disponiveis_db = query.all()
    titulos_receitas = [pdf_generator.normalizar_texto(r.titulo) for r in receitas_disponiveis_db]
    titulos_formatados_para_prompt = "\n- ".join(titulos_receitas) if titulos_receitas else "Nenhuma receita compativel foi encontrada."

    prompt_para_ia = f"""
    Aja como uma nutricionista clínica e esportiva, especialista em culinária brasileira.
    Sua tarefa é criar um plano de refeições SEMANAL (7 dias) detalhado e profissional para um usuário com as seguintes características:
    - Perfil: Sexo: {request.sexo}, Idade: {request.idade} anos, Objetivo: {request.objetivo}
    - Restrições: {', '.join(request.restricoes) if request.restricoes else 'Nenhuma'}
    - Meta Calórica Diária: Aproximadamente {meta_calorica:.0f} kcal.

    REGRAS DE FORMATAÇÃO E CONTEÚDO (OBRIGATÓRIAS):
    1.  **NÃO USE TABELAS MARKDOWN.** A formatação deve ser feita com cabeçalhos (###) e listas de marcadores (-).
    2.  **RESUMO GERAL:** No início, inclua uma introdução e um resumo com a Meta Calórica e a distribuição alvo de MACRONUTRIENTES (Proteínas, Carboidratos, Gorduras) em formato de texto ou lista, **NÃO TABELA**.
    3.  **ESTRUTURA DIÁRIA:** Para CADA DIA, crie um cabeçalho de nível 3 (###) (ex: '### Segunda-Feira').
    4.  **LISTA DE REFEIÇÕES:** Para cada dia, liste as 6 refeições (Café da Manhã, Lanche da Manhã, Almoço, Lanche da Tarde, Jantar, Ceia) usando marcadores simples (-).
        - Exemplo de formato para uma refeição:
          - Cafe da Manha: Vitamina de Banana com Aveia e Pasta de Amendoim. (Kcal: 450, P: 20g, C: 50g, G: 20g)
    5.  **DADOS PRECISOS:** Inclua os valores de Kcal e macronutrientes para CADA refeição. A soma diária deve ser próxima da meta.
    6.  **FOCO EM MICRONUTRIENTES:** No final de cada dia, adicione um parágrafo curto chamado "**Foco em Micronutrientes:**", destacando 1 ou 2 vitaminas/minerais importantes.
    7.  **USO DE RECEITAS:** Para Almoço e Jantar, escolha UMA receita da "LISTA DE RECEITAS DISPONÍVEIS".
    8.  **REFEIÇÃO LIVRE:** No Sábado ou Domingo, substitua UMA refeição (Almoço ou Jantar) por "**Refeição Livre**", sem detalhar calorias.
    9.  **NOME DA RECEITA LIMPO:** Ao usar uma receita da lista, liste *apenas* o nome exato da receita (ex: "Aloo Gobi: Curry Indiano de Batata e Couve-Flor"). NÃO adicione nenhum texto extra como "(Receita da Lista)".

    LISTA DE RECEITAS DISPONÍVEIS PARA ESCOLHA:
    - {titulos_formatados_para_prompt}

    Sua resposta DEVE ser um único objeto JSON válido, sem nenhum texto antes ou depois, contendo as chaves "plano_texto" e "receitas_sugeridas".
    {{
      "plano_texto": "...",
      "receitas_sugeridas": {{ ... }}
    }}
    """
    
    try:
        model = genai.GenerativeModel('models/gemini-flash-latest')
        response = model.generate_content(prompt_para_ia, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        try:
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                response_ia_json = json.loads(json_match.group(0))
            else:
                raise ValueError("Nenhum JSON válido encontrado na resposta da IA.")
        except (json.JSONDecodeError, ValueError) as json_err:
             print(f"ERRO ao decodificar JSON da IA: {json_err}\nResposta recebida:\n{response.text}")
             raise HTTPException(status_code=500, detail="Erro ao processar a resposta da IA. Formato JSON inválido.")
    except Exception as e:
        error_detail = str(e)
        if hasattr(e, 'response') and hasattr(e.response, 'text'): error_detail = e.response.text
        print(f"ERRO da API Gemini: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Erro ao comunicar com a IA: {error_detail}")

    receitas_sugeridas_dict = response_ia_json.get("receitas_sugeridas", {})
    receitas_detalhadas_db = []
    if receitas_sugeridas_dict:
        titulos_ia_limpos = {
            t.lower().strip().replace("(receita da lista)", "").strip() 
            for t in receitas_sugeridas_dict.keys() if t and isinstance(t, str)
        }
        receitas_detalhadas_db = [
            r for r in receitas_disponiveis_db 
            if pdf_generator.normalizar_texto(r.titulo).lower().strip() in titulos_ia_limpos
        ]

    lista_de_compras = pdf_generator.gerar_lista_de_compras_aprimorada(receitas_detalhadas_db)

    receitas_formatadas = []
    for receita in receitas_detalhadas_db:
        dia_sugerido = ""
        titulo_db_limpo = pdf_generator.normalizar_texto(receita.titulo).lower().strip()
        for titulo_ia_original, dia in receitas_sugeridas_dict.items():
             if not isinstance(titulo_ia_original, str): continue
             titulo_ia_limpo = titulo_ia_original.lower().strip().replace("(receita da lista)", "").strip()
             if titulo_db_limpo == titulo_ia_limpo:
                dia_sugerido = dia
                break
        
        ingredientes_formatados = []
        lista_ingredientes_originais = receita.ingredientes if isinstance(receita.ingredientes, list) else []
        for ing in lista_ingredientes_originais:
             if isinstance(ing, dict) and ing.get("texto_original"):
                 ingredientes_formatados.append({"descricao": ing["texto_original"]})
                 
        modo_preparo_limpo = getattr(receita, 'modo_preparo', "") or ""
        modo_preparo_limpo = re.sub(r'^\s*#{1,6}\s*', '', modo_preparo_limpo, flags=re.MULTILINE)
        modo_preparo_limpo = re.sub(r'\*\*', '', modo_preparo_limpo)
        modo_preparo_limpo = re.sub(r'\*', '', modo_preparo_limpo)
        modo_preparo_limpo = re.sub(r'^\s*-\s+', '', modo_preparo_limpo, flags=re.MULTILINE)
        
        # Garante que informacoes_nutricionais é um dicionário antes de acessá-lo
        info_nutri = receita.informacoes_nutricionais if isinstance(receita.informacoes_nutricionais, dict) else {}
        
        receitas_formatadas.append({
            "titulo": getattr(receita, 'titulo', "Receita sem Título"),
            "modo_preparo": modo_preparo_limpo, 
            "ingredientes": ingredientes_formatados,
            "dia_sugerido": dia_sugerido,
            # Use .get() para acessar as chaves do dicionário JSON 'info_nutri'
            # **VERIFIQUE SE ESTES NOMES DE CHAVES ('energia_kcal', etc.) ESTÃO CORRETOS!**
            "calorias": info_nutri.get('energia_kcal', 0),    
            "proteinas": info_nutri.get('proteina_g', 0),       
            "carboidratos": info_nutri.get('carboidrato_g', 0),   
            "gorduras": info_nutri.get('lipideos_g', 0)       # TACO usa 'lipideos_g'
        })

    try:
        plano_texto_md = response_ia_json.get("plano_texto", "Erro: Plano de refeições não gerado pela IA.")
        
        pdf_path = pdf_generator.criar_pdf_plano_excelente(
            plano_texto_md=plano_texto_md, 
            receitas_detalhadas=receitas_formatadas, 
            user_data=request, 
            meta_calorica=meta_calorica, 
            lista_compras=lista_de_compras
        )
        
        task_delete_file = BackgroundTask(os.remove, pdf_path)
        return FileResponse(
            pdf_path, 
            media_type='application/pdf', 
            filename=f"Plano_NutriAI_{request.tipo_plano}.pdf", 
            background=task_delete_file
        )
    except HTTPException as http_err:
         raise http_err
    except Exception as e:
        print(f"ERRO INESPERADO ao gerar PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Erro inesperado ao gerar o arquivo PDF: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "API está funcionando!"}