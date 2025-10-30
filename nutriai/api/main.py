import os
import json
import re # Importado
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from thefuzz import process as fuzz_process # Importado

from . import models, schemas, pdf_generator
from .database import SessionLocal, engine
import google.generativeai as genai

# --- Configuração da API Key (sem alterações) ---
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: raise ValueError("Chave de API GOOGLE_API_KEY não encontrada.")
    genai.configure(api_key=api_key)
except (ValueError, TypeError) as e: print(f"ERRO DE CONFIGURAÇÃO DO GEMINI: {e}")

# --- Criação das tabelas e App FastAPI (sem alterações) ---
models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="NutriAI API", description="API para planejamento de dietas.", version="1.0.0")

# --- Função 'get_db' (sem alterações) ---
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# --- ENDPOINT PRINCIPAL ---
@app.post("/planejar-dieta/", response_class=FileResponse)
def planejar_dieta(request: schemas.UserRequestSchema, db: Session = Depends(get_db)):
    """Gera um plano de dieta completo e retorna como um PDF."""

    # ETAPA 1: CÁLCULO DE CALORIAS (sem alterações)
    if request.sexo == 'masculino':
        meta_calorica = (10 * request.peso_kg) + (6.25 * request.altura_cm) - (5 * request.idade) + 5
    else:
        meta_calorica = (10 * request.peso_kg) + (6.25 * request.altura_cm) - (5 * request.idade) - 161
    fatores_atividade = {"sedentario": 1.2, "leve": 1.375, "moderado": 1.55, "ativo": 1.725}
    meta_calorica *= fatores_atividade.get(request.nivel_atividade, 1.55)
    if request.objetivo == 'perder_peso': meta_calorica -= 500
    elif request.objetivo == 'ganhar_massa': meta_calorica += 500

    # ETAPA 2: BUSCAR RECEITAS DISPONÍVEIS (sem alterações)
    restricao_map = {
        'vegano': models.Receita.is_vegan, 'vegetariano': models.Receita.is_vegetarian, 'sem_gluten': models.Receita.is_gluten_free,
        'sem_lactose': models.Receita.is_lactose_free, 'sem_oleaginosas': models.Receita.is_nut_free,
        'sem_frutos_do_mar': models.Receita.is_seafood_free, 'sem_ovo': models.Receita.is_egg_free, 'sem_soja': models.Receita.is_soy_free
    }
    query = db.query(models.Receita).filter(models.Receita.revisado == True)
    if request.restricoes:
        for restricao in request.restricoes:
            coluna_filtro = restricao_map.get(restricao.lower())
            if coluna_filtro is not None: query = query.filter(coluna_filtro == True)
    receitas_disponiveis_db = query.all()
    mapa_titulos_db = {pdf_generator.normalizar_texto(r.titulo).lower().strip(): r for r in receitas_disponiveis_db if r.titulo}
    titulos_db_normalizados = list(mapa_titulos_db.keys())
    titulos_formatados_para_prompt = "\n- ".join(titulos_db_normalizados) if titulos_db_normalizados else "Nenhuma receita compativel foi encontrada."


    # ETAPA 3: CRIAR O PROMPT PARA A IA (Ajustado para clareza e reforçar regras)
    prompt_para_ia = f"""
    Aja como uma nutricionista clínica e esportiva, especialista em culinária brasileira.
    Sua tarefa é criar um plano de refeições SEMANAL (7 dias) detalhado e profissional para um usuário com as seguintes características:
    - Perfil: Sexo: {request.sexo}, Idade: {request.idade} anos, Objetivo: {request.objetivo}
    - Restrições: {', '.join(request.restricoes) if request.restricoes else 'Nenhuma'}
    - Meta Calórica Diária: Aproximadamente {meta_calorica:.0f} kcal.

    REGRAS DE FORMATAÇÃO E CONTEÚDO (OBRIGATÓRIAS):
    1.  **NÃO USE TABELAS MARKDOWN.** A formatação deve ser feita APENAS com cabeçalhos (###) e listas de marcadores (-). Nenhuma outra formatação markdown (como `|`, `---`, `**`, `*`).
    2.  **RESUMO GERAL:** No início, inclua uma introdução e um resumo com a Meta Calórica e a distribuição alvo de MACRONUTRIENTES (Proteínas, Carboidratos, Gorduras) em formato de texto ou lista, **NÃO TABELA**. Use **negrito** apenas para os nomes dos macros.
    3.  **ESTRUTURA DIÁRIA:** Para CADA DIA, crie um cabeçalho de nível 3 (###) (ex: '### Segunda-Feira').
    4.  **LISTA DE REFEIÇÕES:** Para cada dia, liste as 6 refeições (Café da Manhã, Lanche da Manhã, Almoço, Lanche da Tarde, Jantar, Ceia) usando marcadores simples (-). Use **negrito** APENAS para o nome da refeição (ex: "**Cafe da Manha:**").
        - Exemplo de formato para uma refeição:
          - **Cafe da Manha:** Vitamina de Banana com Aveia e Pasta de Amendoim. (Kcal: 450, P: 20g, C: 50g, G: 20g)
    5.  **DADOS PRECISOS:** Inclua os valores de Kcal e macronutrientes para CADA refeição. A soma diária deve ser próxima da meta. Adicione também a soma total diária no final de cada dia (ex: "**Total Diário (Aprox.):** 2450 Kcal, P: 150g, C: 300g, G: 70g"). Use **negrito** apenas para "Total Diário (Aprox.):".
    6.  **FOCO EM MICRONUTRIENTES:** No final de cada dia, adicione um parágrafo curto chamado "**Foco em Micronutrientes:**", destacando 1 ou 2 vitaminas/minerais importantes. Use **negrito** apenas para "Foco em Micronutrientes:".
    7.  **USO DE RECEITAS:** Para Almoço e Jantar, escolha UMA receita da "LISTA DE RECEITAS DISPONÍVEIS".
    8.  **REFEIÇÃO LIVRE:** No Sábado ou Domingo, substitua UMA refeição (Almoço ou Jantar) por "**Refeição Livre**", sem detalhar calorias. Use **negrito** apenas para "Refeição Livre".
    9.  **NOME DA RECEITA LIMPO:** Ao usar uma receita da lista, liste *apenas* o nome exato da receita (ex: "Aloo Gobi: Curry Indiano de Batata e Couve-Flor"). NÃO adicione nenhum texto extra como "(Receita da Lista)".

    LISTA DE RECEITAS DISPONÍVEIS PARA ESCOLHA:
    - {titulos_formatados_para_prompt}

    Sua resposta DEVE ser um único objeto JSON válido, sem nenhum texto antes ou depois, contendo as chaves "plano_texto" e "receitas_sugeridas". A chave "receitas_sugeridas" deve ser um dicionário onde a chave é o nome EXATO da receita escolhida da lista e o valor é uma string indicando o dia e refeição (ex: "Segunda-Feira (Almoco)").
    {{
      "plano_texto": "...",
      "receitas_sugeridas": {{
          "Estrogonofe Vegano de Soja com Ervas Finas": "Segunda-Feira (Almoco)",
          "Lasanha Vegana de Berinjela com Molho de Proteína de Soja": "Quarta-Feira (Almoco)"
          // ... outras receitas usadas
      }}
    }}
    """

    # ETAPA 4: CHAMAR A IA (sem alterações)
    try:
        model = genai.GenerativeModel('models/gemini-flash-latest')
        response = model.generate_content(prompt_para_ia, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        try:
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match: response_ia_json = json.loads(json_match.group(0))
            else: raise ValueError("Nenhum JSON válido encontrado na resposta da IA.")
        except (json.JSONDecodeError, ValueError) as json_err:
             print(f"ERRO ao decodificar JSON da IA: {json_err}\nResposta recebida:\n{response.text}")
             raise HTTPException(status_code=500, detail="Erro ao processar a resposta da IA. Formato JSON inválido.")
    except Exception as e:
        error_detail = str(e); print(f"ERRO da API Gemini: {error_detail}"); raise HTTPException(status_code=500, detail=f"Erro ao comunicar com a IA: {error_detail}")

    # ETAPA 5: FILTRAR DETALHES DAS RECEITAS - ***LÓGICA FUZZY MATCHING CORRIGIDA v4***
    receitas_sugeridas_dict = response_ia_json.get("receitas_sugeridas", {})
    mapa_receitas_encontradas = {} # {id_receita_db: {"receita": obj_receita, "dia_sugerido": str}}

    if isinstance(receitas_sugeridas_dict, dict) and titulos_db_normalizados:
        # Cria mapa de sugestões da IA: {titulo_limpo_ia: dia_sugerido_ia}
        mapa_ia_sugestoes = {}
        for titulo_ia_raw, dia_sugerido in receitas_sugeridas_dict.items():
            if titulo_ia_raw and isinstance(titulo_ia_raw, str) and dia_sugerido and isinstance(dia_sugerido, str):
                titulo_ia_limpo = pdf_generator.normalizar_texto(titulo_ia_raw).lower().strip().replace("(receita da lista)", "").strip()
                if titulo_ia_limpo and titulo_ia_limpo not in mapa_ia_sugestoes:
                    mapa_ia_sugestoes[titulo_ia_limpo] = dia_sugerido
    
        titulos_ia_para_busca = list(mapa_ia_sugestoes.keys())
        LIMIAR_SIMILARIDADE = 85 # Limiar alto para garantir boa correspondência

        if titulos_ia_para_busca:
            # *** LÓGICA CORRETA ***
            # Para CADA título sugerido pela IA, encontre a MELHOR correspondência no DB
            for titulo_ia, dia in mapa_ia_sugestoes.items():
                # Encontra o melhor match *do banco de dados* para o título da IA
                matches = fuzz_process.extract(titulo_ia, titulos_db_normalizados, limit=1)
                if not matches:
                    continue
                
                melhor_match_db, pontuacao = matches[0]
                
                if pontuacao >= LIMIAR_SIMILARIDADE:
                    receita_db_correspondente = mapa_titulos_db.get(melhor_match_db)
                    if receita_db_correspondente:
                        # Adiciona ao mapa, usando o ID do DB como chave para evitar duplicatas
                        if receita_db_correspondente.id not in mapa_receitas_encontradas:
                             mapa_receitas_encontradas[receita_db_correspondente.id] = {
                                 "receita": receita_db_correspondente,
                                 "dia_sugerido": dia # Usa o dia da sugestão original da IA
                             }
                        else:
                            # Se a IA sugeriu a mesma receita (ex: Almôndegas) para dois dias
                            mapa_receitas_encontradas[receita_db_correspondente.id]["dia_sugerido"] += f", {dia}"
    
    # Pega a lista final de objetos Receita
    receitas_detalhadas_db = [item["receita"] for item in mapa_receitas_encontradas.values()]
    if not receitas_detalhadas_db:
         print("WARN: Nenhuma receita correspondente encontrada após fuzzy matching. Verifique as sugestões da IA e o limiar.")


    # ETAPA 6: GERAR LISTA DE COMPRAS APRIMORADA
    lista_de_compras_bruta = pdf_generator.gerar_lista_de_compras_aprimorada(receitas_detalhadas_db)

    # --- NOVA ETAPA 6.5: OTIMIZAR LISTA DE COMPRAS COM IA (COM CORREÇÃO ORTOGRÁFICA) ---
    lista_compras_otimizada = lista_de_compras_bruta # Define um padrão
    if lista_de_compras_bruta:
        try:
            # Converte a lista de strings em um único texto para a IA
            lista_texto_para_ia = "\n".join(lista_de_compras_bruta)
            
            # PROMPT ATUALIZADO (Inclui Regra 1 para ortografia)
            prompt_otimizacao = f"""
            Aja como um especialista em otimização de listas de compras. Sua tarefa é "limpar", "corrigir" e "consolidar" a lista de compras a seguir, tornando-a pronta para um ser humano usar no supermercado.

            REGRAS OBRIGATÓRIAS:
            1.  **Corrija Erros de Ortografia:** Corrija todos os erros de digitação e formatação.
                - "Graodebico" -> "Grão-de-bico"
                - "Brocoli" -> "Brócolis"
                - "Alhoporó" -> "Alho-poró"
                - "Pimentadoreino" -> "Pimenta-do-reino"

            2.  **Consolide Unidades Lógicas:** Combine unidades diferentes para a forma mais lógica de compra, arredondando para cima.
                - "- Cebola: 3 unidades, (1 colher (sopa), 1/2 xícara)" -> "- Cebola: 4 unidades"
                - "- Alho: 6 cabeças, (5 dentes)" -> "- Alho: 7 cabeças"
                - "- Cominho: 1 colher de sopa e 1 colher (chá)" -> "- Cominho: 1 pote pequeno"

            3.  **Elimine Quantidades Fracionadas/Vagas:** Converta frações (0.5, 1/2) e termos vagos ("a gosto") em unidades de compra reais.
                - "- Açafrão: 0.5 colher de chá" -> "- Açafrão: 1 pote pequeno"
                - "- Molho de soja: 1/2 xícara" -> "- Molho de soja: 1 frasco pequeno"
                - "- Azeitona: a gosto" -> "- Azeitonas: 1 pote pequeno"
                - "- Uvaspassas: a gosto" -> "- Uvas passas: 1 pacote pequeno"

            4.  **Mantenha o Formato:** A resposta DEVE ser uma lista de marcadores ("- Nome do Item: Quantidade").
            5.  **Seja Absoluto:** NÃO inclua NENHUM texto antes ou depois da lista (sem "Aqui está a lista:", "Observações:", etc.).

            LISTA PARA OTIMIZAR:
            {lista_texto_para_ia}
            """
            
            # Reusa o modelo da IA
            model = genai.GenerativeModel('models/gemini-flash-latest')
            response_otimizacao = model.generate_content(prompt_otimizacao)
            
            # Limpa a resposta da IA (remove espaços, etc.)
            texto_otimizado = response_otimizacao.text.strip()
            
            if texto_otimizado:
                # Converte o texto de volta para uma lista de strings
                lista_otimizada_temp = [linha.strip() for linha in texto_otimizado.split('\n') if linha.strip().startswith('-')]
                
                # Garante que não falhou
                if lista_otimizada_temp:
                    lista_compras_otimizada = lista_otimizada_temp
            
            # Se a IA falhar em retornar uma lista válida, o 'lista_compras_otimizada'
            # continuará sendo o 'lista_de_compras_bruta' (nosso fallback)

        except Exception as e_otimizacao:
            print(f"WARN: Falha ao otimizar a lista de compras com IA. Usando a lista original. Erro: {e_otimizacao}")
            lista_compras_otimizada = lista_de_compras_bruta # Fallback em caso de erro
    # --- FIM DA ETAPA 6.5 ---


    # ETAPA 7: FORMATAR DADOS PARA O PDF (COM TODAS AS CORREÇÕES)
    receitas_formatadas = []
    # Regex para limpar macros dos ingredientes (Kcal: ..., P: ..., etc.)
    regex_macros_ingredientes = r'\(\s*Kcal:.*?\)'
    
    for receita_id, data in mapa_receitas_encontradas.items():
        receita = data["receita"]
        dia_sugerido = data["dia_sugerido"]

        ingredientes_formatados = []
        lista_ingredientes_originais = receita.ingredientes if isinstance(receita.ingredientes, list) else []
        for ing in lista_ingredientes_originais:
             if isinstance(ing, dict) and ing.get("texto_original"):
                 texto_original = ing.get("texto_original")
                 # --- Limpa o texto (Kcal: ...) do ingrediente ---
                 texto_limpo = re.sub(regex_macros_ingredientes, '', texto_original, flags=re.IGNORECASE).strip().rstrip(' ,.')
                 if texto_limpo:
                     ingredientes_formatados.append({"descricao": texto_limpo})
        
        
        modo_preparo_limpo = getattr(receita, 'modo_preparo', "") or ""
        
        # --- ***NOVA CORREÇÃO: Limpeza de intros da IA (Dados sujos do DB)*** ---
        # Remove frases como "As instruções foram corrigidas..." [cite: 1439]
        regex_intro_ia = r'^\s*.*(corrigid(a|as)|normalizad(a|as)|padronizad(a|as)|reorganizad(a|as)|formatad(a|as)).*?\n'
        modo_preparo_limpo = re.sub(regex_intro_ia, '', modo_preparo_limpo, flags=re.IGNORECASE).strip()
        # Remove "Modo de Preparo" ou "Instruções de Preparo" duplicados no início [cite: 1491, 1508, 1554]
        modo_preparo_limpo = re.sub(r'^\s*(Modo de Preparo|Instruções de Preparo)\s*\n', '', modo_preparo_limpo, flags=re.IGNORECASE).strip()
        # --- FIM DA NOVA CORREÇÃO ---

        # --- Limpeza Aprimorada v4 do Markdown no Modo de Preparo ---
        # Remove títulos H1-H6 e separadores (***, ---) que estão sozinhos na linha
        modo_preparo_limpo = re.sub(r'^\s*#{1,6}\s*(.*?)\s*#*\s*$', r'**\1**', modo_preparo_limpo, flags=re.MULTILINE)
        modo_preparo_limpo = re.sub(r'^\s*[-*_]{3,}\s*$', '', modo_preparo_limpo, flags=re.MULTILINE)
        # Remove negrito/itálico com asteriscos OU underscores (preserva o texto interno)
        modo_preparo_limpo = re.sub(r'[*_]{1,3}(.*?)[*_]{1,3}', r'\1', modo_preparo_limpo)
        # Remove marcadores de lista no início da linha (*, -, +, 1., 2.)
        modo_preparo_limpo = re.sub(r'^\s*[-*+]\s+', '', modo_preparo_limpo, flags=re.MULTILINE)
        modo_preparo_limpo = re.sub(r'^\s*\d+\.\s+', '', modo_preparo_limpo, flags=re.MULTILINE)
        # Remove espaços extras no início/fim de cada linha
        linhas = [linha.strip() for linha in modo_preparo_limpo.split('\n')]
        # Remove linhas que ficaram vazias após a limpeza
        modo_preparo_limpo = '\n'.join(filter(None, linhas))
        modo_preparo_limpo = re.sub(r'\s{2,}', ' ', modo_preparo_limpo) # Remove espaços múltiplos

        # Acessa o JSON de nutrientes
        info_nutri = receita.informacoes_nutricionais if isinstance(receita.informacoes_nutricionais, dict) else {}

        receitas_formatadas.append({
            "titulo": getattr(receita, 'titulo', "Receita sem Título"),
            "modo_preparo": modo_preparo_limpo, # Usa a versão limpa
            "ingredientes": ingredientes_formatados, # Lista já limpa
            "dia_sugerido": dia_sugerido,

            # --- ***MODIFICAÇÃO: Macros removidos*** ---
            # Conforme solicitado, não vamos mais exibir os macros
            # totais das receitas, pois já são detalhados no plano.
            "calorias": None,    
            "proteinas": None,       
            "carboidratos": None,   
            "gorduras": None
            # --- FIM DA MODIFICAÇÃO ---
        })

    # ETAPA 8: GERAR E RETORNAR O PDF (ATUALIZADO)
    try:
        plano_texto_md = response_ia_json.get("plano_texto", "Erro: Plano de refeições não gerado pela IA.")

        # DEBUG Prints (ATUALIZADO)
        print("\n--- DEBUG ANTES DE GERAR PDF v6 (Otimização + Limpeza de Receita) ---")
        print(f"Número de receitas formatadas: {len(receitas_formatadas)}")
        if receitas_formatadas:
             macros_receita_0 = {k: receitas_formatadas[0].get(k) for k in ['calorias', 'proteinas', 'carboidratos', 'gorduras']}
             print(f"Exemplo macros receita 0: {macros_receita_0}")
        print(f"Número de itens na lista de compras (Otimizada): {len(lista_compras_otimizada)}")
        if lista_compras_otimizada:
            # Mostra alguns itens para verificar a correção
            print("Exemplos de itens da lista otimizada:")
            for item in lista_compras_otimizada[:5]:
                print(f"  {item}")
        print("--- FIM DEBUG v6 ---")

        pdf_path = pdf_generator.criar_pdf_plano_excelente(
            plano_texto_md=plano_texto_md,
            receitas_detalhadas=receitas_formatadas,
            user_data=request,
            meta_calorica=meta_calorica,
            lista_compras=lista_compras_otimizada # <-- PASSANDO A LISTA OTIMIZADA
        )

        task_delete_file = BackgroundTask(os.remove, pdf_path)
        return FileResponse(pdf_path, media_type='application/pdf', filename=f"Plano_NutriAI_{request.tipo_plano}.pdf", background=task_delete_file)
    except HTTPException as http_err: raise http_err
    except Exception as e:
        print(f"ERRO INESPERADO ao gerar PDF: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro inesperado ao gerar o arquivo PDF: {str(e)}")

# Endpoint de saúde (sem alterações)
@app.get("/health")
def health_check():
    return {"status": "API está funcionando!"}