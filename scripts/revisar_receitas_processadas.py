# scripts/revisar_receitas_processadas.py
import json
import os
import time
import argparse
import google.generativeai as genai
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Lock
from google.api_core import exceptions
from pathlib import Path

# --- CONFIGURAÇÕES ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')

ORIGINAL_JSON_FOLDER = Path(__file__).resolve().parent.parent / "data" / "receitas_processadas"

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: raise ValueError("Chave de API GOOGLE_API_KEY não encontrada.")
    genai.configure(api_key=api_key)
    print("API do Google Gemini configurada com sucesso.")
except (ValueError, TypeError) as e:
    print(f"ERRO DE CONFIGURAÇÃO: {e}")
    exit()

# --- CONTROLE DE QUOTA ---
quota_exceeded_event = Event()
print_lock = Lock()
quota_hit_message_printed = False

# --- FUNÇÃO DE NORMALIZAÇÃO DE TEXTO ---
def normalizar_texto(texto: str) -> str:
    if not texto or not isinstance(texto, str): return ""
    try: return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        try: return texto.encode('utf-8', 'ignore').decode('utf-8')
        except Exception: return texto

# --- FUNÇÕES DE CORREÇÃO COM IA (CORRIGIDAS) ---
def handle_quota_error(e):
    global quota_hit_message_printed
    with print_lock:
        if not quota_hit_message_printed:
            print("\n" + "="*80); print("❌ QUOTA DA API ATINGIDA..."); print(f"   Detalhe: {e}"); print("="*80 + "\n"); quota_hit_message_printed = True
    quota_exceeded_event.set()

def corrigir_titulo_receita_com_gemini(titulo: str):
    if quota_exceeded_event.is_set(): return titulo
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"Corrija e padronize o seguinte título de receita: '{titulo}'. Retorne APENAS o texto do título corrigido."
    try:
        response = model.generate_content(prompt)
        return response.text.strip().strip('"').strip("'")
    except exceptions.ResourceExhausted as e:
        handle_quota_error(e)
        return titulo
    except Exception as e:
        print(f"  -> Aviso (Título): {e}")
        raise e

def corrigir_modo_preparo_com_gemini(texto_preparo: str):
    if quota_exceeded_event.is_set(): return texto_preparo
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"Corrija, normalize e formate as seguintes instruções de receita em uma lista numerada (1., 2., 3., etc.).\nTexto original: '{texto_preparo}'"
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except exceptions.ResourceExhausted as e:
        handle_quota_error(e)
        return texto_preparo
    except Exception as e:
        print(f"  -> Aviso (Preparo): {e}")
        raise e

def analisar_ingrediente_com_gemini(texto_ingrediente: str):
    if quota_exceeded_event.is_set(): return None
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"Analise: '{texto_ingrediente}'.\nRetorne um JSON com: \"nome_ingrediente\", \"quantidade\", \"unidade\", \"observacao\"."
    try:
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        dados = json.loads(response.text)
        if isinstance(dados, list): dados = dados[0] if dados else None
        if not isinstance(dados, dict): return None
        dados['texto_original'] = texto_ingrediente
        return dados
    except exceptions.ResourceExhausted as e:
        handle_quota_error(e)
        return None
    except Exception as e:
        print(f"  -> Aviso (Ingrediente): {e}")
        raise e

# --- [MODIFICADO] FUNÇÃO PARA CLASSIFICAR RESTRIÇÕES ---
def classificar_restricoes_com_gemini(titulo: str, ingredientes_json: list) -> dict:
    """
    Analisa a lista de ingredientes e classifica as restrições da receita.
    """
    if quota_exceeded_event.is_set(): return None
    
    # Pega apenas o nome dos ingredientes para a análise
    nomes_ingredientes = [item.get('nome_ingrediente', item.get('texto_original', '')) for item in ingredientes_json]
    lista_ingredientes_str = ", ".join(filter(None, nomes_ingredientes))
    
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"""
    Analise a seguinte receita com base no título e na lista de ingredientes.
    Retorne um JSON com OITO chaves booleanas: 
    "is_vegan", "is_vegetarian", "is_gluten_free", "is_lactose_free", 
    "is_nut_free", "is_seafood_free", "is_egg_free", "is_soy_free".

    Regras de Classificação:
    1.  **is_vegetarian**: 'false' se contiver carne, peixe, frango, frutos do mar.
    2.  **is_vegan**: 'false' se contiver QUALQUER produto animal (carne, peixe, laticínios, ovos, mel, gelatina).
    3.  **is_gluten_free**: 'false' se contiver trigo, cevada, centeio, aveia (não especificada), farinha de trigo, pão.
    4.  **is_lactose_free**: 'false' se contiver leite, queijo, manteiga, iogurte (não especificados 'sem lactose').
    5.  **is_nut_free**: 'false' se contiver amendoim, castanhas, nozes, amêndoas, pistache, macadâmia.
    6.  **is_seafood_free**: 'false' se contiver peixe, camarão, lula, polvo, mexilhões, ostras.
    7.  **is_egg_free**: 'false' se contiver ovos.
    8.  **is_soy_free**: 'false' se contiver soja, tofu, shoyu, missô, leite de soja.

    Título da Receita: "{titulo}"
    Lista de Ingredientes: "{lista_ingredientes_str}"

    Retorne APENAS o objeto JSON.
    """
    
    default_response = {
        "is_vegan": False, "is_vegetarian": False, "is_gluten_free": False, "is_lactose_free": False,
        "is_nut_free": False, "is_seafood_free": False, "is_egg_free": False, "is_soy_free": False
    }
    
    try:
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        classificacoes = json.loads(response.text)
        
        # Garante que todas as chaves esperadas estão presentes
        for key in default_response:
            if key not in classificacoes or not isinstance(classificacoes[key], bool):
                classificacoes[key] = default_response[key] # Usa o padrão se a chave estiver ausente ou mal formatada
                
        return classificacoes
    
    except exceptions.ResourceExhausted as e:
        handle_quota_error(e)
        return None # Se der cota, retorna None
    except Exception as e:
        print(f"  -> Aviso (Classificação): {e}")
        raise e # Força a falha da receita

# --- FUNÇÃO DE BUSCA NO BANCO ---
def buscar_receitas_para_revisar(conn, limit=None, force=False):
    """Busca ID e URL das receitas para revisar."""
    query_str = "SELECT id, url FROM receitas WHERE processado_pela_llm = TRUE"
    if not force:
        # Força a revisão apenas das que ainda não foram revisadas (com a nova lógica)
        query_str += " AND revisado = FALSE"
    query_str += " ORDER BY id;"
    if limit:
        query_str = query_str.replace(";", f" LIMIT {limit};")
    query = text(query_str)
    return conn.execute(query).fetchall()

# --- LÓGICA DE PROCESSAMENTO (MODIFICADA) ---
def processar_uma_receita(row):
    """
    Pega id/url do banco, lê o JSON original, processa com IA e retorna dados corrigidos.
    Se qualquer etapa da IA falhar, retorna None.
    """
    if quota_exceeded_event.is_set(): return None
    receita_id, url = row
    print(f"Iniciando processamento da Receita ID {receita_id} (Arquivo)...")

    try:
        if not url:
             print(f"   -> ⚠️ Receita ID {receita_id} sem URL no banco. Pulando.")
             return None

        # --- LÓGICA DE ENCONTRAR O ARQUIVO (sem alterações) ---
        slug = url.split('/')[-1].replace('.html', '')
        if '-' in slug and slug.split('-', 1)[0].isdigit():
            filename_base = slug.split('-', 1)[1]
        elif '_' in slug and slug.split('_', 1)[0].isdigit():
             filename_base = slug.split('_', 1)[1]
        else:
            filename_base = slug
        filename_underscore = f"{filename_base.replace('-', '_')}.json"
        filepath_underscore = ORIGINAL_JSON_FOLDER / filename_underscore
        filename_hyphen = f"{filename_base.replace('_', '-')}.json"
        filepath_hyphen = ORIGINAL_JSON_FOLDER / filename_hyphen
        filepath = None
        if filepath_underscore.is_file():      filepath = filepath_underscore
        elif filepath_hyphen.is_file():        filepath = filepath_hyphen
        else:
            print(f"   -> ⚠️ Arquivo JSON não encontrado para ID {receita_id}. Tentativas:")
            print(f"      - {filepath_underscore}")
            print(f"      - {filepath_hyphen}")
            return None

        # --- LEITURA DO ARQUIVO ORIGINAL ---
        with open(filepath, 'r', encoding='utf-8') as f:
            dados_originais = json.load(f)

        titulo_original = dados_originais.get('titulo', '')
        ingredientes_originais_lista = dados_originais.get('ingredientes', [])
        modo_preparo_original_lista = dados_originais.get('modo_preparo', [])
        modo_preparo_original_str = "\n".join(modo_preparo_original_lista)

        # --- PROCESSAMENTO COM IA (agora dentro do try...except) ---
        titulo_final = corrigir_titulo_receita_com_gemini(normalizar_texto(titulo_original))
        time.sleep(0.5)

        modo_preparo_final = corrigir_modo_preparo_com_gemini(normalizar_texto(modo_preparo_original_str))
        time.sleep(0.5)

        ingredientes_novos = []
        for texto_ingrediente_original in ingredientes_originais_lista:
            if quota_exceeded_event.is_set(): break

            texto_normalizado = normalizar_texto(texto_ingrediente_original)
            if not texto_normalizado: continue

            ingrediente_corrigido = analisar_ingrediente_com_gemini(texto_normalizado)
            if ingrediente_corrigido:
                ingredientes_novos.append(ingrediente_corrigido)
            else:
                 if not quota_exceeded_event.is_set():
                      raise ValueError(f"Falha ao analisar ingrediente: {texto_normalizado}")
                 ingredientes_novos.append({"texto_original": texto_normalizado})
            time.sleep(0.5)
        
        if quota_exceeded_event.is_set():
            print(f"   -> ⚠️ Processamento da Receita ID {receita_id} interrompido devido à cota.")
            return None
        
        # --- CHAMADA À FUNÇÃO DE CLASSIFICAÇÃO ---
        print(f"   -> Classificando restrições da Receita ID {receita_id}...")
        classificacoes = classificar_restricoes_com_gemini(titulo_final, ingredientes_novos)
        time.sleep(0.5) # Respeita a cota

        if not classificacoes: # Se a classificação falhar (por cota ou outro erro)
            if not quota_exceeded_event.is_set():
                raise ValueError(f"Falha ao classificar restrições da Receita ID {receita_id}")
            print(f"   -> ⚠️ Classificação da Receita ID {receita_id} interrompida.")
            return None
        
        # --- [MODIFICADO] Retorna o resultado completo ---
        return {
            "id": receita_id, 
            "titulo": titulo_final, 
            "ingredientes": ingredientes_novos, 
            "modo_preparo": modo_preparo_final,
            "classificacoes": classificacoes
        }

    except Exception as e:
        if not quota_exceeded_event.is_set():
            print(f"❌ Erro ao processar a receita ID {receita_id}: {e}")
        return None

# --- [MODIFICADO] FUNÇÃO DE ATUALIZAÇÃO NO BANCO ---
def atualizar_receita_revisada(conn, receita_id, titulo_novo, ingredientes_novos, modo_preparo_novo, classificacoes_novas):
    update_query = text("""
        UPDATE receitas SET
            titulo = :titulo, 
            ingredientes = :ingredientes, 
            modo_preparo = :modo_preparo, 
            revisado = TRUE,
            is_vegan = :is_vegan,
            is_vegetarian = :is_vegetarian,
            is_gluten_free = :is_gluten_free,
            is_lactose_free = :is_lactose_free,
            is_nut_free = :is_nut_free,
            is_seafood_free = :is_seafood_free,
            is_egg_free = :is_egg_free,
            is_soy_free = :is_soy_free
        WHERE id = :id;
    """)
    ingredientes_json = json.dumps(ingredientes_novos if ingredientes_novos is not None else [], ensure_ascii=False)
    
    # Combina os parâmetros
    params = {
        "id": receita_id, 
        "titulo": titulo_novo, 
        "ingredientes": ingredientes_json, 
        "modo_preparo": modo_preparo_novo
    }
    # Adiciona as novas classificações ao dicionário de parâmetros
    params.update(classificacoes_novas)
    
    conn.execute(update_query, params)

# --- FLUXO PRINCIPAL ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Revisa receitas lendo JSONs originais, de forma paralela.")
    parser.add_argument("--limit", type=int, help="Número máximo de receitas para revisar.")
    parser.add_argument("--force", action="store_true", help="Força a revisão de TODAS as receitas (ignora a flag 'revisado').")
    parser.add_argument("--workers", type=int, default=10, help="Número de workers paralelos (padrão: 10).")
    args = parser.parse_args()
    
    if not ORIGINAL_JSON_FOLDER.is_dir():
        print(f"❌ ERRO: A pasta de receitas processadas '{ORIGINAL_JSON_FOLDER}' não foi encontrada.")
        exit()

    try:
        db_url = URL.create(drivername="postgresql+psycopg2", username=os.getenv("POSTGRES_USER"),password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST"),port=os.getenv("POSTGRES_PORT"), database=os.getenv("POSTGRES_DB"))
        engine = create_engine(db_url)
        print("✔️ Conectado ao PostgreSQL.")
    except Exception as e:
        print(f"❌ ERRO ao conectar ao PostgreSQL: {e}"); exit()

    print("\nBuscando IDs e URLs das receitas no banco de dados...")
    with engine.connect() as conn:
        receitas_para_revisar = buscar_receitas_para_revisar(conn, limit=args.limit, force=args.force)
    
    total_receitas = len(receitas_para_revisar)
    if not total_receitas: print("✅ Nenhuma receita para revisar."); exit()

    print(f"Iniciando revisão de {total_receitas} receitas com {args.workers} workers paralelos (lendo arquivos originais)...")
    receitas_atualizadas = 0
    receitas_falhadas = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_receita = {executor.submit(processar_uma_receita, row): row for row in receitas_para_revisar}
        
        for future in as_completed(future_to_receita):
            resultado = future.result()
            if resultado:
                try:
                    with engine.begin() as conn:
                        # --- [MODIFICADO] ---
                        atualizar_receita_revisada(
                            conn, 
                            resultado["id"], 
                            resultado["titulo"],
                            resultado["ingredientes"], 
                            resultado["modo_preparo"],
                            resultado["classificacoes"] # <-- NOVO
                        )
                    receitas_atualizadas += 1
                    print(f"   -> ✅ Receita ID {resultado['id']} foi ATUALIZADA e CLASSIFICADA. ({receitas_atualizadas}/{total_receitas})")
                except Exception as e:
                    print(f"❌ Erro ao ATUALIZAR a receita ID {resultado['id']} no banco. Erro: {e}")
                    receitas_falhadas += 1
            else:
                if not quota_exceeded_event.is_set():
                    receitas_falhadas += 1

    # --- Relatório Final ---
    print("\n" + "="*50); print("Processo de revisão concluído.")
    print(f"✅ {receitas_atualizadas} de {total_receitas} receitas foram atualizadas com sucesso.")
    if receitas_falhadas > 0:
        print(f"⚠️ {receitas_falhadas} receitas falharam no processamento (ver logs) e NÃO foram marcadas como 'revisado'.")
    if quota_exceeded_event.is_set():
        print(f"\nATENÇÃO: A cota da API foi atingida."); 
        print("As receitas restantes (e as que falharam) NÃO foram revisadas. Rode o script novamente após a cota resetar.")
    print("="*50)