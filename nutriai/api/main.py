# api/main.py
import os
import json
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from . import models, schemas, pdf_generator
from .database import SessionLocal, engine
import google.generativeai as genai

# Configuração da API Key
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: raise ValueError("Chave de API GOOGLE_API_KEY não encontrada.")
    genai.configure(api_key=api_key)
except (ValueError, TypeError) as e:
    print(f"ERRO DE CONFIGURAÇÃO DO GEMINI: {e}")

# Criação das tabelas e App FastAPI
models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="NutriAI API", description="API para planejamento de dietas.", version="1.0.0")

# Função 'get_db'
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- ENDPOINT PRINCIPAL ---
@app.post("/planejar-dieta/", response_class=FileResponse)
def planejar_dieta(request: schemas.UserRequestSchema, db: Session = Depends(get_db)):
    """
    Gera um plano de dieta completo (semanal ou mensal) e retorna como um PDF.
    """
    # ETAPA 1: CÁLCULO DE CALORIAS
    if request.sexo == 'masculino':
        meta_calorica = (10 * request.peso_kg) + (6.25 * request.altura_cm) - (5 * request.idade) + 5
    else:
        meta_calorica = (10 * request.peso_kg) + (6.25 * request.altura_cm) - (5 * request.idade) - 161
    
    fatores_atividade = {"sedentario": 1.2, "leve": 1.375, "moderado": 1.55, "ativo": 1.725}
    meta_calorica *= fatores_atividade.get(request.nivel_atividade, 1.55)
    
    if request.objetivo == 'perder_peso': meta_calorica -= 500
    elif request.objetivo == 'ganhar_massa': meta_calorica += 500

    # ETAPA 2: BUSCAR RECEITAS DISPONÍVEIS
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

    # ETAPA 3: CRIAR O "PROMPT DE NUTRICIONISTA" APRIMORADO
    prompt_para_ia = f"""
    Aja como uma nutricionista clínica e esportiva, especialista em culinária brasileira.
    Sua tarefa é criar um plano de refeições SEMANAL (7 dias) detalhado e profissional para um usuário com as seguintes características:
    - Perfil: Sexo: {request.sexo}, Idade: {request.idade} anos, Objetivo: {request.objetivo}
    - Restrições: {', '.join(request.restricoes) if request.restricoes else 'Nenhuma'}
    - Meta Calórica Diária: Aproximadamente {meta_calorica:.0f} kcal.

    REGRAS DE FORMATAÇÃO E CONTEÚDO (OBRIGATÓRIAS):
    1.  **NÃO USE TABELAS MARKDOWN.** A formatação deve ser feita com cabeçalhos e listas de marcadores.
    2.  **RESUMO GERAL:** No início, inclua uma introdução e um resumo com a Meta Calórica e a distribuição alvo de MACRONUTRIENTES (Proteínas, Carboidratos, Gorduras).
    3.  **ESTRUTURA DIÁRIA:** Para CADA DIA, crie um cabeçalho de nível 3 (###) (ex: '### Segunda-Feira').
    4.  **LISTA DE REFEIÇÕES:** Para cada dia, liste as 6 refeições (Café da Manhã, Lanche da Manhã, Almoço, Lanche da Tarde, Jantar, Ceia) usando marcadores.
        - Exemplo de formato para uma refeição:
          - Cafe da Manha: Vitamina de Banana com Aveia e Pasta de Amendoim. (Kcal: 450, P: 20g, C: 50g, G: 20g)
    5.  **DADOS PRECISOS:** Inclua os valores de Kcal e macronutrientes para CADA refeição. A soma diária deve ser próxima da meta.
    6.  **FOCO EM MICRONUTRIENTES:** No final de cada dia, adicione um parágrafo curto chamado "Foco em Micronutrientes:", destacando 1 ou 2 vitaminas/minerais importantes.
    7.  **USO DE RECEITAS:** Para Almoço e Jantar, escolha UMA receita da "LISTA DE RECEITAS DISPONÍVEIS".
    8.  **REFEIÇÃO LIVRE:** No Sábado ou Domingo, substitua UMA refeição (Almoço ou Jantar) por "Refeição Livre", sem detalhar calorias.
    9.  **NOME DA RECEITA LIMPO:** Ao usar uma receita da lista, liste *apenas* o nome exato da receita (ex: "Aloo Gobi: Curry Indiano de Batata e Couve-Flor"). NÃO adicione nenhum texto extra como "(Receita da Lista)".

    LISTA DE RECEITAS DISPONÍVEIS PARA ESCOLHA:
    - {titulos_formatados_para_prompt}

    Sua resposta DEVE ser um único objeto JSON, sem nenhum texto ou formatação adicional.
    {{
      "plano_texto": "Um texto formatado em markdown contendo a introdução, o resumo e o plano para cada dia, SEM usar tabelas.",
      "receitas_sugeridas": {{
          "Nome da Receita 1": "Dia da Semana (Refeicao)",
          "Nome da Receita 2": "Dia da Semana (Refeicao)"
      }}
    }}
    """
    
    # ETAPA 4: CHAMAR A IA
    try:
        model = genai.GenerativeModel('models/gemini-flash-latest')
        response = model.generate_content(prompt_para_ia, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        response_ia_json = json.loads(response.text)
    except Exception as e:
        error_detail = str(e)
        if hasattr(e, 'response') and hasattr(e.response, 'text'): error_detail = e.response.text
        print(f"ERRO da API Gemini: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Erro ao comunicar com a IA: {error_detail}")

    # ETAPA 5: FILTRAR DETALHES DAS RECEITAS ESCOLHIDAS PELA IA (CORRIGIDO)
    receitas_sugeridas_dict = response_ia_json.get("receitas_sugeridas", {})
    receitas_detalhadas_db = []
    if receitas_sugeridas_dict:
        # Limpa o "(Receita da Lista)" que a IA pode adicionar
        titulos_ia_limpos = {
            t.lower().strip().replace("(receita da lista)", "").strip() 
            for t in receitas_sugeridas_dict.keys() if t
        }
        
        # Compara com os títulos limpos do banco de dados
        receitas_detalhadas_db = [
            r for r in receitas_disponiveis_db 
            if pdf_generator.normalizar_texto(r.titulo).lower().strip() in titulos_ia_limpos
        ]

    # ETAPA 6: GERAR LISTA DE COMPRAS APRIMORADA
    # Esta função agora vai receber a lista COMPLETA de receitas
    lista_de_compras = pdf_generator.gerar_lista_de_compras_aprimorada(receitas_detalhadas_db)

    # ETAPA 7: FORMATAR DADOS PARA O PDF
    receitas_formatadas = []
    for receita in receitas_detalhadas_db:
        dia_sugerido = ""
        # Loop para encontrar a receita no dicionário da IA (com e sem limpeza)
        titulo_db_limpo = pdf_generator.normalizar_texto(receita.titulo).lower().strip()
        for titulo_ia_original, dia in receitas_sugeridas_dict.items():
            titulo_ia_limpo = titulo_ia_original.lower().strip().replace("(receita da lista)", "").strip()
            if titulo_db_limpo == titulo_ia_limpo:
                dia_sugerido = dia # Ex: "Segunda-Feira (Almoco)"
                break
        
        ingredientes_formatados = [{"descricao": ing.get("texto_original", "")} for ing in (receita.ingredientes or []) if ing.get("texto_original")]
        receitas_formatadas.append({
            "titulo": receita.titulo,
            "modo_preparo": receita.modo_preparo,
            "ingredientes": ingredientes_formatados,
            "dia_sugerido": dia_sugerido # Adiciona o dia aqui
        })

    # ETAPA 8: GERAR E RETORNAR O PDF
    try:
        plano_texto_md = response_ia_json.get("plano_texto", "Erro ao gerar plano.")
        pdf_path = pdf_generator.criar_pdf_plano_aprimorado(
            plano_texto=plano_texto_md, 
            receitas_detalhadas=receitas_formatadas, 
            user_data=request, 
            meta_calorica=meta_calorica, 
            lista_compras=lista_de_compras
        )
        
        task_delete_file = BackgroundTask(os.remove, pdf_path)
        return FileResponse(pdf_path, media_type='application/pdf', filename=f"Plano_NutriAI_{request.tipo_plano}.pdf", background=task_delete_file)
    except Exception as e:
        print(f"ERRO ao gerar PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar o arquivo PDF: {str(e)}")

# Endpoint de saúde
@app.get("/health")
def health_check():
    return {"status": "API está funcionando!"}