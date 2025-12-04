import pandas as pd
import unicodedata
import random
import difflib
import re
import os
import time
import argparse
import json
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from sqlalchemy import create_engine, text, exc as sqlalchemy_exc
from sqlalchemy.engine import URL, Engine
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event

# --- Configuração do Ambiente ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if not os.path.exists(dotenv_path):
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')
    print(f"Arquivo .env carregado de: {dotenv_path}")
else:
    print("Aviso: Arquivo .env não encontrado.")

class QuotaExceededError(Exception): pass

# --- Configuração da API Google Gemini ---
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: raise ValueError("Chave GOOGLE_API_KEY não encontrada.")
    genai.configure(api_key=api_key)
    print("API do Google Gemini configurada.")
except ValueError as e:
    print(f"ERRO DE CONFIGURAÇÃO: {e}"); exit()

# --- Variáveis Globais ---
api_disponivel = True
api_quota_event = Event()
print_lock = Lock()
db_lock = Lock() 

# --- Constantes (Mantidas do seu código original) ---
BLACKLISTA_IGNORAR = {'água', 'agua', 'sal', 'gelo', 'a gosto', 'quanto baste', 'q.b.', 'pimenta', 'tempero', 'cominho', 'louro'}
MAPEAMENTO_TACO = {"ovo": "Ovo, de galinha, inteiro, cru", "ovos": "Ovo, de galinha, inteiro, cru"}
MAPEAMENTO_TACO_NORMALIZADO = {''.join(c for c in unicodedata.normalize('NFD', k) if unicodedata.category(c) != 'Mn'): v for k, v in MAPEAMENTO_TACO.items()}

# --- Funções Auxiliares ---

def limpar_numero(valor) -> float:
    """Extrai um float de uma string ou retorna 0.0."""
    if not valor: return 0.0
    try:
        # Remove tudo que não for dígito ou ponto (ex: "aprox 150g" -> 150)
        match = re.search(r"[\d\.]+", str(valor).replace(',', '.'))
        return float(match.group()) if match else 0.0
    except (ValueError, TypeError): return 0.0

def corrigir_texto_quebrado(texto: str):
    """Corrige encoding latin-1/utf-8."""
    if not isinstance(texto, str): return texto
    try: return texto.encode('latin-1').decode('utf-8')
    except: return texto

def carregar_tabela_taco(caminho_csv: str = "data/processed/tabela_taco_processada.csv"):
    try:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        caminho_completo = os.path.join(project_dir, caminho_csv)
        if not os.path.exists(caminho_completo): caminho_completo = caminho_csv

        df = pd.read_csv(caminho_completo)
        df['alimento_normalizado'] = df['alimento'].astype(str).str.lower().apply(lambda x: ''.join(c for c in unicodedata.normalize('NFD', x) if unicodedata.category(c) != 'Mn'))
        df.set_index('alimento_normalizado', inplace=True)
        print("Tabela TACO carregada e normalizada.")
        return df
    except Exception as e:
        print(f"ERRO ao carregar TACO: {e}"); return None

def padronizar_unidade(unidade: str) -> str:
    if not unidade: return 'unidade'
    u_normalizada = ''.join(c for c in unicodedata.normalize('NFD', str(unidade).lower()) if unicodedata.category(c) != 'Mn')
    u_limpa = u_normalizada.replace('(', '').replace(')', '').replace('.', '').strip()
    
    mapeamento = {
        'xicara': 'xicara', 'xicaras': 'xicara', 'xicara de cha': 'xicara', 
        'colher de sopa': 'colher de sopa', 'colheres de sopa': 'colher de sopa', 'sopa': 'colher de sopa', 'colher': 'colher de sopa',
        'colher de cha': 'colher de cha', 'colheres de cha': 'colher de cha', 'colherzinha': 'colher de cha',
        'dente': 'dente', 'dentes': 'dente', 'copo': 'copo', 'lata': 'lata', 'pacote': 'pacote', 
        'grama': 'g', 'gramas': 'g', 'g': 'g', 'quilo': 'kg', 'kg': 'kg', 'litro': 'l', 'ml': 'ml', 
        'unidade': 'unidade', 'fatia': 'fatia'
    }
    # Tenta achar a chave no texto da unidade (ex: "xicaras de cha" -> "xicara")
    for chave, valor in mapeamento.items():
        if chave in u_limpa: return valor
    return mapeamento.get(u_limpa, 'unidade') # Default seguro

# Conversões manuais "Gold Standard" para evitar chamadas de IA em coisas óbvias
CONVERSOES_MANUAIS = {
    ('agua', 'xicara'): 240.0, ('agua', 'colher de sopa'): 15.0,
    ('farinha de trigo', 'xicara'): 120.0, ('farinha de trigo', 'colher de sopa'): 7.5,
    ('acucar', 'xicara'): 160.0, ('acucar', 'colher de sopa'): 12.0,
    ('arroz', 'xicara'): 185.0, ('manteiga', 'colher de sopa'): 12.0,
    ('oleo', 'xicara'): 200.0, ('oleo', 'colher de sopa'): 15.0, ('oleo', 'colher de cha'): 4.0,
    ('azeite', 'colher de sopa'): 13.0, ('azeite', 'colher de cha'): 4.5,
    ('leite', 'xicara'): 240.0, ('leite', 'copo'): 200.0,
    ('ovo', 'unidade'): 50.0, ('cebola', 'unidade'): 100.0, ('tomate', 'unidade'): 90.0,
    ('dente de alho', 'unidade'): 5.0, ('alho', 'dente'): 5.0
}

# --- Banco de Dados ---
def preparar_banco(conn):
    # Tabela de Nutrientes (Cache IA - Já existia)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS taco_complementar (
            alimento TEXT PRIMARY KEY, calorias REAL, proteina REAL, 
            lipideos REAL, carboidratos REAL, fibras REAL, texto_completo TEXT
        );
    """))
    # NOVA: Tabela de Pesos Inteligentes (Cache IA para Gramas)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS pesos_medidas_ia (
            id SERIAL PRIMARY KEY,
            ingrediente TEXT,
            unidade TEXT,
            peso_gramas REAL,
            UNIQUE(ingrediente, unidade)
        );
    """))

# --- Funções de IA (Gemini) ---

def ia_descobrir_peso_unitario(ingrediente: str, unidade: str) -> float:
    """Pergunta à IA quantos gramas tem X unidade de Y ingrediente."""
    global api_disponivel
    if not api_disponivel or api_quota_event.is_set(): return 0.0

    with print_lock: print(f"    [PESO] Descobrindo quantos gramas tem 1 {unidade} de '{ingrediente}'...")
    time.sleep(1.1) # Rate limit seguro
    
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"""
    Responda APENAS com um número (ponto flutuante).
    Quantos gramas pesa, em média, 1 {unidade} de {ingrediente}?
    Se for uma unidade abstrata (ex: "a gosto") responda 0.
    Se for líquido (ml), considere a densidade (ex: 1ml óleo = 0.9g).
    Exemplo: "1 colher de sopa de farinha" -> Responda: 7.5
    Resposta:
    """
    try:
        response = model.generate_content(prompt)
        peso = limpar_numero(response.text)
        return peso
    except google_exceptions.ResourceExhausted:
        api_quota_event.set()
        raise QuotaExceededError("Cota Peso")
    except: return 0.0

def ia_descobrir_nutrientes(ingrediente: str) -> dict:
    """Descobre a tabela nutricional de 100g do ingrediente."""
    global api_disponivel
    if not api_disponivel or api_quota_event.is_set(): return None
    
    with print_lock: print(f"    [NUTRI] Aprendendo tabela nutricional de '{ingrediente}'...")
    time.sleep(1.1)
    
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f'Forneça a informação nutricional para 100 gramas de "{ingrediente}". Responda APENAS com JSON: {{"calorias": float, "proteina": float, "lipideos": float, "carboidratos": float, "fibras": float}}. Se for inválido (ex: água), retorne tudo 0.'
    try:
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        d = json.loads(response.text)
        return {
            'alimento': ingrediente,
            'calorias': limpar_numero(d.get('calorias')),
            'proteina': limpar_numero(d.get('proteina')),
            'lipideos': limpar_numero(d.get('lipideos')),
            'carboidratos': limpar_numero(d.get('carboidratos')),
            'fibras': limpar_numero(d.get('fibras')),
            'texto_completo': response.text
        }
    except google_exceptions.ResourceExhausted:
        api_quota_event.set(); raise QuotaExceededError("Cota Nutri")
    except: return None

# --- Lógica de Conversão e Cálculo ---

def obter_peso_em_gramas(conn, engine, nome_ing: str, unidade_raw: str, qtd: float):
    """
    Converte a medida da receita para gramas (Matemática -> Manual -> Cache -> IA).
    """
    unidade = padronizar_unidade(unidade_raw)
    
    # 1. Conversão Direta (Matemática)
    if unidade in ['g', 'gramas', 'ml']: return qtd # Simplificação 1g=1ml para genéricos
    if unidade in ['kg', 'quilos', 'litro', 'l']: return qtd * 1000.0
    
    nome_norm = ''.join(c for c in unicodedata.normalize('NFD', nome_ing.lower()) if unicodedata.category(c) != 'Mn')

    # 2. Dicionário Manual (Rápido)
    peso_unitario = CONVERSOES_MANUAIS.get((nome_norm, unidade))
    if peso_unitario: return qtd * peso_unitario
    
    # 3. Cache do Banco (pesos_medidas_ia)
    res = conn.execute(text("SELECT peso_gramas FROM pesos_medidas_ia WHERE ingrediente = :i AND unidade = :u"), 
                       {"i": nome_norm, "u": unidade}).fetchone()
    if res:
        return qtd * res[0]

    # 4. IA (Se não estivermos em cota)
    if not api_quota_event.is_set():
        peso_aprendido = ia_descobrir_peso_unitario(nome_norm, unidade)
        if peso_aprendido > 0:
            # Salva no cache
            with db_lock:
                try:
                    with engine.connect() as c_conn:
                        with c_conn.begin():
                            c_conn.execute(text("""
                                INSERT INTO pesos_medidas_ia (ingrediente, unidade, peso_gramas)
                                VALUES (:i, :u, :p) ON CONFLICT(ingrediente, unidade) DO NOTHING
                            """), {"i": nome_norm, "u": unidade, "p": peso_aprendido})
                except: pass
            return qtd * peso_aprendido
            
    # Se tudo falhar, usa defaults conservadores (melhor que zero)
    defaults = {'xicara': 200.0, 'copo': 200.0, 'colher de sopa': 15.0, 'colher de cha': 5.0, 'unidade': 80.0}
    return qtd * defaults.get(unidade, 0.0)

def encontrar_alimento(conn, engine: Engine, nome_ingrediente: str, df_taco: pd.DataFrame):
    """Busca nutrientes: Cache -> TACO -> IA."""
    global api_disponivel
    if not nome_ingrediente: return None

    # 1. Cache DB (taco_complementar)
    res = conn.execute(text("SELECT calorias, proteina, lipideos, carboidratos, fibras FROM taco_complementar WHERE alimento = :a"), {"a": nome_ingrediente}).fetchone()
    if res: return pd.Series(res._asdict())

    # 2. TACO Memória (CSV)
    nome_norm = ''.join(c for c in unicodedata.normalize('NFD', nome_ingrediente.lower()) if unicodedata.category(c) != 'Mn')
    # Mapeamento manual (ovos -> ovo)
    nome_mapeado = MAPEAMENTO_TACO_NORMALIZADO.get(nome_norm, nome_norm)
    
    if nome_mapeado in df_taco.index: return df_taco.loc[nome_mapeado]
    
    matches = difflib.get_close_matches(nome_mapeado, df_taco.index.tolist(), n=1, cutoff=0.85)
    if matches: return df_taco.loc[matches[0]]

    # 3. IA
    if api_disponivel and not api_quota_event.is_set():
        dados = ia_descobrir_nutrientes(nome_ingrediente)
        if dados:
            with db_lock:
                try:
                    with engine.connect() as c_conn:
                        with c_conn.begin():
                            c_conn.execute(text("""
                                INSERT INTO taco_complementar (alimento, calorias, proteina, lipideos, carboidratos, fibras, texto_completo)
                                VALUES (:alimento, :calorias, :proteina, :lipideos, :carboidratos, :fibras, :texto_completo)
                                ON CONFLICT(alimento) DO NOTHING
                            """), dados)
                except Exception as e: print(f"Erro cache nutri: {e}")
            return pd.Series(dados)
    return None

# --- Worker Principal ---

def marcar_erro_receita(conn, receita_id):
    """Marca a receita com erro para não travar o processo."""
    try:
        conn.execute(text("UPDATE receitas SET tem_erro = TRUE WHERE id = :id"), {"id": receita_id})
    except: pass

def salvar_calculo_sucesso(conn, receita_id, totais):
    conn.execute(text("""
        UPDATE receitas SET 
            informacoes_nutricionais = :info, 
            nutrientes_calculados = TRUE,
            tem_erro = FALSE 
        WHERE id = :id
    """), {"info": json.dumps(totais), "id": receita_id})

def processar_receita(receita, df_taco, engine):
    if api_quota_event.is_set(): return (receita.id, False, "Cota")

    with engine.connect() as conn:
        with conn.begin():
            try:
                if not receita.ingredientes:
                    marcar_erro_receita(conn, receita.id)
                    return (receita.id, False, "Sem ingr")

                totais = {'calorias': 0.0, 'proteina': 0.0, 'lipideos': 0.0, 'carboidratos': 0.0, 'fibras': 0.0}
                
                for ing in receita.ingredientes:
                    if api_quota_event.is_set(): raise QuotaExceededError()
                    
                    nome = corrigir_texto_quebrado(ing.get("nome_ingrediente"))
                    unidade = ing.get("unidade")
                    
                    # Tenta converter quantidade (string "1 1/2" -> float 1.5)
                    qtd_str = str(ing.get("quantidade", "0")).replace(',', '.')
                    try:
                        qtd = float(sum(float(n)/float(d) for n, d in [x.split('/') for x in qtd_str.split() if '/' in x])) if '/' in qtd_str else float(qtd_str)
                    except: qtd = 0.0

                    if not nome or qtd <= 0 or nome.lower() in BLACKLISTA_IGNORAR: continue

                    # PASSO 1: Descobrir peso em gramas (IA ou Manual)
                    peso_gramas = obter_peso_em_gramas(conn, engine, nome, unidade, qtd)
                    
                    if peso_gramas <= 0: continue 

                    # PASSO 2: Pegar nutrientes de 100g (TACO ou IA)
                    nutri = encontrar_alimento(conn, engine, nome, df_taco)

                    # PASSO 3: O Cálculo Final
                    if nutri is not None and not nutri.empty:
                        fator = peso_gramas / 100.0
                        for k in totais:
                            if k in nutri and pd.notna(nutri[k]):
                                totais[k] += float(nutri[k]) * fator
                
                salvar_calculo_sucesso(conn, receita.id, totais)
                return (receita.id, True, None)

            except QuotaExceededError:
                return (receita.id, False, "Cota")
            except Exception as e:
                marcar_erro_receita(conn, receita.id)
                return (receita.id, False, str(e))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=10)
    parser.add_argument('--clear-cache', action='store_true')
    parser.add_argument('ids', nargs='*', type=int)
    args = parser.parse_args()

    df_taco = carregar_tabela_taco()
    if df_taco is None: exit()

    try:
        db_url = URL.create("postgresql+psycopg2", username=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST"), port=os.getenv("POSTGRES_PORT"), database=os.getenv("POSTGRES_DB"))
        engine = create_engine(db_url, pool_size=args.workers, max_overflow=5)
        print("DB Conectado.")
    except Exception as e: print(f"Erro DB: {e}"); exit()

    with engine.connect() as conn:
        if args.clear_cache:
            with conn.begin(): 
                conn.execute(text("DELETE FROM taco_complementar"))
                try: conn.execute(text("DELETE FROM pesos_medidas_ia")) 
                except: pass
            print("CACHES LIMPOS.")
        
        with conn.begin(): preparar_banco(conn)
        
        # Query Principal: Filtra receitas prontas (Script 1), não calculadas (Script 2) e sem erro
        query = "SELECT id, titulo, ingredientes FROM receitas WHERE ingredientes IS NOT NULL AND processado_pela_llm = TRUE AND nutrientes_calculados = FALSE AND tem_erro = FALSE"
        if args.ids: query += f" AND id IN ({','.join(map(str, args.ids))})"
        
        receitas = conn.execute(text(query)).fetchall()

    print(f"Calculando {len(receitas)} receitas...")
    
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(processar_receita, r, df_taco, engine): r for r in receitas}
        for f in as_completed(futures):
            if api_quota_event.is_set(): break
            rid, suc, msg = f.result()
            with print_lock:
                if suc: print(f" -> SUCESSO ID {rid}")
                elif "Cota" not in str(msg): print(f" -> FALHA ID {rid} (Erro marcado): {msg}")
    
    print("Fim do processamento.")