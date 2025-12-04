import json
import os
import time
import re
from threading import Event, Lock
import argparse
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, exc as sqlalchemy_exc # Importe sqlalchemy_exc
from sqlalchemy.engine import URL

# Garante que o .env seja carregado da raiz do projeto
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if not os.path.exists(dotenv_path):
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')
    print(f"Arquivo .env carregado de: {dotenv_path}")
else:
    print("Aviso: Arquivo .env não encontrado nas localizações padrão.")

class QuotaExceededError(Exception):
    """Exceção para quando a cota da API é atingida."""
    pass

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Chave de API GOOGLE_API_KEY não encontrada.")
    genai.configure(api_key=api_key)
    print("API do Google Gemini configurada com sucesso.")
except (ValueError, TypeError) as e:
    print(f"ERRO DE CONFIGURAÇÃO: {e}")
    exit()

# ---- Variáveis Globais para Workers ----
quota_exceeded_event = Event()
print_lock = Lock()
api_calls_count_lock = Lock()
api_calls_count = 0
# ----------------------------------------

def analisar_ingrediente_com_gemini(texto_ingrediente: str):
    """Usa a IA para analisar e padronizar um ingrediente."""
    global api_calls_count
    if quota_exceeded_event.is_set(): return None 
    
    model = genai.GenerativeModel('models/gemini-flash-latest')
    
    prompt = f"""
    Analise o seguinte texto: '{texto_ingrediente}'.
    REGRAS CRÍTICAS:
    1. Se o texto NÃO for um ingrediente real (ex: "Massa", "Recheio"), retorne APENAS a palavra "IGNORE".
    2. Se houver alternativas (ex: "azeite ou óleo"), escolha APENAS o primeiro ingrediente (neste caso, "azeite").
    3. Se houver múltiplos ingredientes (ex: "sal, pimenta e salsinha"), extraia APENAS o primeiro (neste caso, "sal").
    4. Retorne um único objeto JSON com as chaves: "nome_ingrediente", "quantidade", "unidade", "observacao".

    REGRAS DE EXTRAÇÃO:
    - "nome_ingrediente": O nome PADRONIZADO (ex: "cebola", "filé mignon", "farinha de trigo").
    - "observacao": Detalhes extras (ex: "picadinha", "cortado em tiras").
    - "unidade": Padronize para o singular (ex: "xícara").

    Exemplos de Resposta:
    - Para o texto "2 xicaras de bifes de filé mignon cortados em tiras", retorne: {{"nome_ingrediente": "filé mignon", "quantidade": "2", "unidade": "xícara", "observacao": "bifes cortados em tiras"}}
    - Para o texto "sal, pimenta e salsinha a gosto", retorne: {{"nome_ingrediente": "sal", "quantidade": null, "unidade": null, "observacao": "a gosto"}}
    - Para o texto "2 colheres de azeite ou óleo", retorne: {{"nome_ingrediente": "azeite", "quantidade": "2", "unidade": "colher", "observacao": null}}
    - Para o texto "Cobertura:", retorne: IGNORE
    """
    
    try:
        time.sleep(0.5) 
        response = model.generate_content(prompt)
        with api_calls_count_lock: api_calls_count += 1
        texto_resposta = response.text.strip()
        
        if texto_resposta == "IGNORE":
            return "IGNORE"

        json_match = re.search(r'\{.*\}', texto_resposta, re.DOTALL)
        if not json_match:
            return None
        
        dados = json.loads(json_match.group(0))
        if not isinstance(dados, dict):
            return None

        dados['texto_original'] = texto_ingrediente
        return dados
        
    except google_exceptions.ResourceExhausted as e:
        quota_exceeded_event.set() 
        with print_lock: print(f"\n!!! QUOTA ATINGIDA (Ingrediente) !!!\n")
        raise QuotaExceededError(f"Cota: {e}")
    except Exception as e:
        with print_lock: print(f"   -> Erro IA (Ingrediente) '{texto_ingrediente}': {e}")
        return None

def corrigir_titulo_receita_com_gemini(titulo: str, retries=3, delay=2):
    """Usa a IA para corrigir e padronizar o título."""
    global api_calls_count
    if quota_exceeded_event.is_set(): return titulo 
    
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"Corrija e padronize o seguinte título de receita: '{titulo}'. Retorne APENAS o texto corrigido."
    for attempt in range(retries):
        try:
            time.sleep(0.5)
            response = model.generate_content(prompt)
            with api_calls_count_lock: api_calls_count += 1
            titulo_corrigido = response.text.strip().strip('"').strip("'")
            if titulo_corrigido: return titulo_corrigido
        except google_exceptions.ResourceExhausted as e: 
            quota_exceeded_event.set()
            raise QuotaExceededError(f"Cota: {e}")
        except Exception:
            time.sleep(delay)
    return titulo

def classificar_restricoes_com_gemini(titulo: str, ingredientes_json: list) -> dict:
    """Classifica as restrições alimentares."""
    global api_calls_count
    if quota_exceeded_event.is_set(): raise QuotaExceededError("Cota atingida.")
    
    nomes = [item.get('nome_ingrediente', item.get('texto_original', '')) for item in ingredientes_json]
    lista_str = ", ".join(filter(None, nomes))
    
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"""
    Analise a receita: "{titulo}" (Ingredientes: {lista_str}).
    Retorne JSON com 8 booleanos: 
    "is_vegan", "is_vegetarian", "is_gluten_free", "is_lactose_free", 
    "is_nut_free", "is_seafood_free", "is_egg_free", "is_soy_free".
    Retorne APENAS o JSON.
    """
    
    default = {"is_vegan": False, "is_vegetarian": False, "is_gluten_free": False, "is_lactose_free": False,
               "is_nut_free": False, "is_seafood_free": False, "is_egg_free": False, "is_soy_free": False}
    
    try:
        time.sleep(0.5)
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        with api_calls_count_lock: api_calls_count += 1
        
        match = re.search(r'\{.*\}', response.text.strip(), re.DOTALL)
        if not match: return default
            
        classif = json.loads(match.group(0))
        for k in default:
            if k not in classif: classif[k] = default[k]
        return classif
    
    except google_exceptions.ResourceExhausted as e:
        quota_exceeded_event.set()
        raise QuotaExceededError(f"Cota: {e}")
    except Exception:
        return default

def buscar_receitas(conn, mode='new', limit=None):
    # Filtramos "tem_erro = FALSE" para não insistir no erro
    where_clauses = ["ingredientes_brutos IS NOT NULL", "tem_erro = FALSE"]
    
    if mode == 'new':
        where_clauses.append("processado_pela_llm = FALSE")
    elif mode == 'all':
        pass 

    query_str = f"SELECT id, titulo, ingredientes_brutos FROM receitas WHERE {' AND '.join(where_clauses)} ORDER BY id;"
    
    if limit:
        query_str = query_str.replace(";", f" LIMIT {limit};")
        
    return conn.execute(text(query_str)).fetchall()

def marcar_receita_com_erro(conn, receita_id):
    """Marca a receita como problemática para não tentar de novo."""
    try:
        conn.execute(text("UPDATE receitas SET tem_erro = TRUE WHERE id = :id"), {"id": receita_id})
    except Exception as e:
        with print_lock: print(f"   -> ERRO ao marcar flag de erro ID {receita_id}: {e}")

def salvar_sucesso(conn, dados):
    """Salva os dados processados."""
    query = text("""
        UPDATE receitas SET
            titulo = :titulo,
            ingredientes = :ingredientes,
            processado_pela_llm = TRUE,
            tem_erro = FALSE,
            revisado = TRUE,
            is_vegan = :is_vegan,
            is_vegetarian = :is_vegetarian,
            is_gluten_free = :is_gluten_free,
            is_lactose_free = :is_lactose_free,
            is_nut_free = :is_nut_free,
            is_seafood_free = :is_seafood_free,
            is_egg_free = :is_egg_free,
            is_soy_free = :is_soy_free,
            nutrientes_calculados = FALSE,
            informacoes_nutricionais = NULL
        WHERE id = :id
    """)
    params = {
        "titulo": dados["titulo"],
        "ingredientes": json.dumps(dados["ingredientes"], ensure_ascii=False),
        "id": dados["receita_id"]
    }
    params.update(dados["classificacoes"])
    
    # Executa a query. Se der erro de integridade (titulo duplicado), vai lançar exceção
    conn.execute(query, params)

def processar_receita_completa(row):
    """
    Retorna uma tupla: (id, sucesso, dados_ou_erro)
    """
    if quota_exceeded_event.is_set():
        return (row[0], False, "Cota excedida")
        
    receita_id, titulo_bruto, ingredientes_brutos = row
    
    try:
        # Tratamento de título
        try: titulo_enc = titulo_bruto.encode('latin1').decode('utf-8')
        except: titulo_enc = titulo_bruto
        
        titulo_final = corrigir_titulo_receita_com_gemini(titulo_enc)

        if not ingredientes_brutos:
            classif = classificar_restricoes_com_gemini(titulo_final, [])
            return (receita_id, True, {
                "receita_id": receita_id, "titulo": titulo_final, 
                "ingredientes": [], "classificacoes": classif
            })
        
        lista_ingredientes = []
        for texto in ingredientes_brutos:
            if quota_exceeded_event.is_set(): raise QuotaExceededError("Cota")
            if not texto.strip(): continue

            dados = analisar_ingrediente_com_gemini(texto)
            if dados == "IGNORE": continue
            if dados: lista_ingredientes.append(dados)
        
        classif = classificar_restricoes_com_gemini(titulo_final, lista_ingredientes)

        return (receita_id, True, {
            "receita_id": receita_id,
            "titulo": titulo_final,
            "ingredientes": lista_ingredientes,
            "classificacoes": classif
        })
    
    except QuotaExceededError:
        return (receita_id, False, "Cota excedida")
    except Exception as e:
        return (receita_id, False, f"Erro geral: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-m', '--mode', choices=['new', 'all'], default='new')
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    try:
        db_url = URL.create(
            drivername="postgresql+psycopg2", username=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST"),
            port=os.getenv("POSTGRES_PORT"), database=os.getenv("POSTGRES_DB"),
            query={"client_encoding": "utf8"}
        )
        engine = create_engine(db_url)
        print("Conectado ao PostgreSQL.")
    except Exception as e:
        print(f"ERRO Conexão DB: {e}"); exit()
    
    try:
        with engine.connect() as conn_leitura:
            receitas = buscar_receitas(conn_leitura, mode=args.mode, limit=args.limit)
        
        if not receitas:
            print("Nenhuma receita para processar.")
        else:
            print(f"Processando {len(receitas)} receitas com {args.workers} workers...")

        sucessos = 0
        falhas = 0

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(processar_receita_completa, row): row for row in receitas}
            
            for future in as_completed(futures):
                if quota_exceeded_event.is_set():
                    for f in futures: f.cancel()
                    break

                try:
                    rid, sucesso, payload = future.result()
                    
                    if sucesso:
                        # TENTA SALVAR
                        try:
                            with engine.begin() as conn:
                                salvar_sucesso(conn, payload)
                            sucessos += 1
                            with print_lock: print(f"   -> SUCESSO ID {rid} ({sucessos}/{len(receitas)})")
                        
                        # CAPTURA ERROS DE DUPLICIDADE (IntegrityError)
                        except sqlalchemy_exc.IntegrityError as e_integrity:
                            # Se der erro de título duplicado, marca como ERRO no banco
                            with engine.begin() as conn:
                                marcar_receita_com_erro(conn, rid)
                            falhas += 1
                            with print_lock: print(f"   -> FALHA ID {rid} (Título Duplicado): Marcada com erro.")
                        
                        # OUTROS ERROS SQL
                        except Exception as e_salvar:
                             # Também marca como erro para não travar o fluxo
                            with engine.begin() as conn:
                                marcar_receita_com_erro(conn, rid)
                            falhas += 1
                            with print_lock: print(f"   -> FALHA ID {rid} (Erro ao Salvar): {e_salvar}")

                    else:
                        # Falha no processamento da IA
                        msg_erro = str(payload)
                        if "Cota" not in msg_erro:
                            with engine.begin() as conn:
                                marcar_receita_com_erro(conn, rid)
                            falhas += 1
                            with print_lock: print(f"   -> FALHA ID {rid} (Erro IA): {msg_erro}")
                        
                except Exception as e:
                    with print_lock: print(f"   -> CRITICAL ERROR: {e}")

    except KeyboardInterrupt:
        print("\nInterrupção manual.")
    finally:
        print(f"\nFim. Sucessos: {sucessos} | Falhas Marcadas: {falhas}")
        if quota_exceeded_event.is_set():
            print("COTA ATINGIDA. As receitas não processadas serão tentadas amanhã.")