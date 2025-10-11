# scripts/calcular_nutrientes.py
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

# --- CONFIGURAÇÃO ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')

class QuotaExceededError(Exception): pass

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: raise ValueError("Chave de API do Google (GOOGLE_API_KEY) não encontrada.")
    genai.configure(api_key=api_key)
    print("API do Google Gemini configurada.")
except ValueError as e:
    print(f"ERRO DE CONFIGURAÇÃO DA API: {e}"); exit()

# --- FUNÇÕES AUXILIARES (sem alterações significativas) ---
def corrigir_texto_quebrado(texto: str):
    if not isinstance(texto, str): return texto
    try: return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError): return texto

BLACKLISTA_IGNORAR = {'água', 'agua', 'sal', 'gelo', 'a gosto', 'quanto baste', 'q.b.'}
MAPEAMENTO_TACO = {"ovo": "Ovo, de galinha, inteiro, cru", "ovos": "Ovo, de galinha, inteiro, cru"} # Reduzido para exemplo
MAPEAMENTO_TACO_NORMALIZADO = {''.join(c for c in unicodedata.normalize('NFD', k) if unicodedata.category(c) != 'Mn'): v for k, v in MAPEAMENTO_TACO.items()}

def carregar_tabela_taco(caminho_csv: str = "data/processed/tabela_taco_processada.csv"):
    try:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        caminho_completo = os.path.join(project_dir, caminho_csv)
        df = pd.read_csv(caminho_completo)
        df['alimento_normalizado'] = df['alimento'].astype(str).str.lower().apply(lambda x: ''.join(c for c in unicodedata.normalize('NFD', x) if unicodedata.category(c) != 'Mn'))
        df.set_index('alimento_normalizado', inplace=True)
        print("✔️ Tabela TACO carregada e normalizada com sucesso.")
        return df
    except Exception as e:
        print(f"❌ ERRO ao carregar a Tabela TACO: {e}"); return None

def converter_para_gramas(ingrediente: dict) -> float:
    # Função de conversão de gramas (simplificada para manter o foco, a sua original é boa)
    # Adapte conforme sua necessidade
    return float(ingrediente.get('quantidade_em_gramas', 0.0))

# --- FUNÇÕES PRINCIPAIS (COM A LÓGICA NOVA) ---

def criar_tabela_cache(conn):
    conn.execute(text("CREATE TABLE IF NOT EXISTS taco_complementar (alimento TEXT PRIMARY KEY, calorias REAL, proteina REAL, lipideos REAL, carboidratos REAL, fibras REAL, texto_completo TEXT);"))
    print("✔️ Tabela de cache 'taco_complementar' garantida no PostgreSQL.")

def tentar_aprender_nutrientes_com_ia(nome_ingrediente: str) -> dict | None:
    """
    Usa a lógica do seu script de estruturação para aprender sobre um novo ingrediente.
    Força a resposta em JSON e é muito mais confiável.
    """
    print(f"   -> Aprendendo sobre '{nome_ingrediente}' com a IA...")
    time.sleep(1.1)
    
    # Modelo do seu script de estruturação, que sabemos que funciona no seu ambiente.
    model = genai.GenerativeModel('models/gemini-flash-latest')
    
    prompt = f'Forneça a informação nutricional para 100 gramas de "{nome_ingrediente}". Responda APENAS com um único objeto JSON com as chaves "calorias", "proteina", "lipideos", "carboidratos", e "fibras". Se o ingrediente for inválido ou não tiver dados (ex: "água", "sal"), retorne um JSON com valores 0.'
    
    try:
        # Usando a configuração do seu script para forçar a resposta em JSON
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
        )
        dados = json.loads(response.text)
        
        nutrientes = {
            'alimento': nome_ingrediente,
            'calorias': float(dados.get('calorias', 0)),
            'proteina': float(dados.get('proteina', 0)),
            'lipideos': float(dados.get('lipideos', 0)),
            'carboidratos': float(dados.get('carboidratos', 0)),
            'fibras': float(dados.get('fibras', 0)),
            'texto_completo': response.text
        }
        print(f"   -> ✅ IA aprendeu: '{nome_ingrediente}'")
        return nutrientes

    except google_exceptions.ResourceExhausted as e:
        raise QuotaExceededError(f"Cota da API do Gemini excedida: {e}")
    except Exception as e:
        print(f"      -> Erro na API do Gemini durante o aprendizado: {e}")
        return None

def encontrar_alimento(conn, nome_ingrediente: str, df_taco: pd.DataFrame, api_disponivel: bool):
    """Busca o alimento no cache, na TACO local, e por último na IA."""
    if not nome_ingrediente or nome_ingrediente.lower() in BLACKLISTA_IGNORAR:
        return None

    # 1. Busca no cache 'taco_complementar'
    cache_query = text("SELECT calorias, proteina, lipideos, carboidratos, fibras FROM taco_complementar WHERE alimento = :alimento")
    resultado_cache = conn.execute(cache_query, {"alimento": nome_ingrediente}).fetchone()
    if resultado_cache:
        return pd.Series(resultado_cache._asdict())

    # 2. Busca na Tabela TACO local
    nome_normalizado = ''.join(c for c in unicodedata.normalize('NFD', nome_ingrediente.lower()) if unicodedata.category(c) != 'Mn')
    nome_mapeado = MAPEAMENTO_TACO_NORMALIZADO.get(nome_normalizado)
    nome_final_busca = ''.join(c for c in unicodedata.normalize('NFD', nome_mapeado.lower()) if unicodedata.category(c) != 'Mn') if nome_mapeado else nome_normalizado
    if nome_final_busca in df_taco.index:
        return df_taco.loc[nome_final_busca]
    
    # 3. Busca por similaridade
    matches = difflib.get_close_matches(nome_final_busca, df_taco.index.tolist(), n=1, cutoff=0.8)
    if matches:
        return df_taco.loc[matches[0]]

    # 4. Aprender com IA
    if api_disponivel:
        dados_aprendidos = tentar_aprender_nutrientes_com_ia(nome_ingrediente)
        if dados_aprendidos:
            # Salva no banco e retorna os dados para uso imediato
            insert_query = text("""
                INSERT INTO taco_complementar (alimento, calorias, proteina, lipideos, carboidratos, fibras, texto_completo)
                VALUES (:alimento, :calorias, :proteina, :lipideos, :carboidratos, :fibras, :texto_completo)
                ON CONFLICT(alimento) DO NOTHING
            """)
            conn.execute(insert_query, dados_aprendidos)
            # Remove chaves que não são nutrientes para o retorno
            dados_aprendidos.pop('alimento', None)
            dados_aprendidos.pop('texto_completo', None)
            return pd.Series(dados_aprendidos)
            
    return None

def salvar_nutrientes(conn, receita_id, totais):
    update_query = text("UPDATE receitas SET informacoes_nutricionais = :info, nutrientes_calculados = TRUE WHERE id = :id")
    conn.execute(update_query, {"info": json.dumps(totais), "id": receita_id})

# --- BLOCO PRINCIPAL (COM A ESTRUTURA CORRETA) ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calcula nutrientes de receitas.")
    parser.add_argument("-l", "--limit", type=int, help="Número máximo de receitas para processar.")
    args = parser.parse_args()

    df_taco = carregar_tabela_taco()
    if df_taco is None: exit()

    try:
        db_url = URL.create(drivername="postgresql+psycopg2", username=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST"), port=os.getenv("POSTGRES_PORT"), database=os.getenv("POSTGRES_DB"), query={"client_encoding": "utf8"})
        engine = create_engine(db_url)
        print("✔️ Conectado ao PostgreSQL.")
    except Exception as e:
        print(f"❌ ERRO ao conectar ao PostgreSQL: {e}"); exit()
        
    api_disponivel = True
    
    # Pega a lista de receitas para processar fora do loop principal
    receitas_para_calcular = []
    with engine.connect() as conn:
        criar_tabela_cache(conn)
        query = text("SELECT id, titulo, ingredientes FROM receitas WHERE processado_pela_llm = TRUE AND nutrientes_calculados = FALSE ORDER BY id")
        if args.limit:
            query = text(str(query) + f" LIMIT {args.limit}")
        receitas_para_calcular = conn.execute(query).fetchall()

    total_a_calcular = len(receitas_para_calcular)
    if not total_a_calcular:
        print("Nenhuma receita nova para calcular.")
    else:
        print(f"Encontradas {total_a_calcular} receitas para calcular os nutrientes. Iniciando...")

    for i, receita in enumerate(receitas_para_calcular):
        print(f"\n[{i+1}/{total_a_calcular}] Processando Receita ID {receita.id} ('{corrigir_texto_quebrado(receita.titulo)}')")
        
        # PADRÃO DE TRANSAÇÃO ATUALIZADO: UMA TRANSAÇÃO POR RECEITA
        with engine.begin() as conn:
            try:
                if not receita.ingredientes:
                    print("   -> AVISO: Receita sem ingredientes estruturados. Pulando.")
                    continue

                totais = {'calorias': 0.0, 'proteina': 0.0, 'lipideos': 0.0, 'carboidratos': 0.0, 'fibras': 0.0}
                sucesso_total = True

                for ing in receita.ingredientes:
                    nome_ing = corrigir_texto_quebrado(ing.get("nome_ingrediente"))
                    # Adapte a linha abaixo para usar sua função de conversão para gramas
                    peso_g = float(ing.get("quantidade", 0)) # Placeholder, use sua função aqui!
                    
                    if not nome_ing or peso_g <= 0:
                        continue
                        
                    dados_nutricionais = encontrar_alimento(conn, nome_ing, df_taco, api_disponivel)

                    if dados_nutricionais is not None and not dados_nutricionais.empty:
                        fator = peso_g / 100.0
                        for nutriente in totais.keys():
                            if nutriente in dados_nutricionais and pd.notna(dados_nutricionais[nutriente]):
                                totais[nutriente] += float(dados_nutricionais[nutriente]) * fator
                    else:
                        print(f"   -> ❌ AVISO: Falha ao encontrar/aprender sobre '{nome_ing}'. A receita não será calculada.")
                        sucesso_total = False
                        break # Pára de processar os ingredientes desta receita

                if sucesso_total:
                    salvar_nutrientes(conn, receita.id, totais)
                    print(f"   -> ✅ Nutrientes calculados e salvos.")

            except QuotaExceededError:
                api_disponivel = False
                print("\n\n!!! ATENÇÃO: Cota da API excedida. O aprendizado será desativado. !!!\n")
            except Exception as e_receita:
                print(f"   -> ❌ Erro inesperado ao processar a receita. Alterações desfeitas. Erro: {e_receita}")
                # A transação sofre rollback automático aqui por causa do 'with engine.begin()'

    if engine: engine.dispose()
    print("\nProcesso de cálculo de nutrientes concluído.")