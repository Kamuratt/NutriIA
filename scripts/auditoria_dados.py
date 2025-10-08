# scripts/auditoria_dados.py
import pandas as pd
import unicodedata
import random
import difflib
import re
import os
import time
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv

# --- Configuração ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')

class QuotaExceededError(Exception):
    pass

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: raise ValueError("Chave de API não encontrada.")
    genai.configure(api_key=api_key)
except ValueError as e:
    print(f"ERRO DE CONFIGURAÇÃO DA API: {e}"); exit()

# --- Funções e Constantes ---
def corrigir_texto_quebrado(texto: str):
    if not texto: return texto
    try: return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError): return texto

BLACKLISTA_IGNORAR = {
    'água', 'agua', 'sal', 'gelo', 'palito de dente', 'papel chumbo', 'receita de', 'a gosto', 'quanto baste', 'q.b.', 
    'fritadeira elétrica', 'cravo-da-índia', 'ervas finas', 'pimenta biquinho', 'cravo', 'água morna', 'açúcar ou adoçante', 
    'becel amanteigado', 'becel', 'canela em pau', 'doritos grande', 'essência de baunilha', 'folhas de hortelã', 
    'frutas (morango, uva ou pessego)', 'garam masala'
}

MAPEAMENTO_TACO = {
    "acucar mascavo": "Açúcar, mascavo", "acucar cristal": "Açúcar, cristal", "leite": "Leite, de vaca, integral, pó", 
    "leite em po": "Leite, de vaca, integral, pó", "oleo": "Óleo, de soja", "fermento": "Fermento em pó, químico", 
    "bacon": "Toucinho, frito", "peito de frango": "Frango, peito, sem pele, cru", "leite de coco": "Leite, de coco", 
    "carne moida": "Carne, bovina, acém, moído, cru", "amido de milho": "Milho, amido, cru", "maisena": "Milho, amido, cru", 
    "azeite": "Azeite, de oliva, extra virgem", "molho de tomate": "Tomate, molho industrializado", "requeijao": "Queijo, requeijão, cremoso", 
    "abobrinha": "Abobrinha, italiana, crua", "cheiro-verde": "Salsa, crua", "salsinha": "Salsa, crua", 
    "ovo": "Ovo, de galinha, inteiro, cru", "ovos": "Ovo, de galinha, inteiro, cru", "alho": "Alho, cru", "cebola": "Cebola, crua", 
    "batata": "Batata, inglesa, crua", "peito de frango temperado , cozido e desfiado": "Frango, peito, sem pele, cozido",
    "coco em flocos": "Coco, cru", "amendoim torrado": "Amendoim, torrado, salgado", "amendoim torrado e moído": "Amendoim, torrado, salgado", 
    "abóbora": "Abóbora, moranga, crua", "arroz": "Arroz, tipo 1, cozido", "açúcar": "Açúcar, cristal", 
    "azeite extra virgem": "Azeite, de oliva, extra virgem", "batata palha": "Batata, frita, tipo chips, industrializada", 
    "calabresa": "Lingüiça, porco, frita", "canela": "Canela, pó", "canela em po": "Canela, pó", "cebolinha": "Cebolinha, crua",
    "cheiro verde": "Salsa, crua", "ervilha": "Ervilha, enlatada, drenada", "fuba para polvilhar": "Milho, fubá, cru", 
    "goiabada": "Goiaba, doce, cascão"
}
MAPEAMENTO_TACO_NORMALIZADO = {''.join(c for c in unicodedata.normalize('NFD', k) if unicodedata.category(c) != 'Mn'): v for k, v in MAPEAMENTO_TACO.items()}

def carregar_tabela_taco(caminho_csv: str = "data/processed/tabela_taco_processada.csv"):
    try:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        caminho_completo = os.path.join(project_dir, caminho_csv)
        df = pd.read_csv(caminho_completo)
        df['alimento_normalizado'] = df['alimento'].astype(str).str.lower().apply(lambda x: ''.join(c for c in unicodedata.normalize('NFD', x) if unicodedata.category(c) != 'Mn'))
        df.set_index('alimento_normalizado', inplace=True)
        return df
    except Exception as e:
        print(f"❌ AVISO: Não foi possível carregar a Tabela TACO: {e}"); return None

def carregar_cache_taco(conn) -> set:
    try:
        return {corrigir_texto_quebrado(row[0]) for row in conn.execute(text("SELECT alimento FROM taco_complementar;")).fetchall()}
    except Exception: return set()

def criar_tabela_mapeamento_cache(conn):
    query = text("CREATE TABLE IF NOT EXISTS mapeamento_cache (nome_ingrediente TEXT PRIMARY KEY, nome_taco TEXT);")
    conn.execute(query)

def tentar_mapeamento_automatico_com_ia(nome_ingrediente: str, lista_alimentos_taco: list, conn):
    cache_query = text("SELECT nome_taco FROM mapeamento_cache WHERE nome_ingrediente = :nome_ing")
    resultado = conn.execute(cache_query, {"nome_ing": nome_ingrediente}).fetchone()
    if resultado:
        return resultado[0] if resultado[0] != 'IGNORE' else None

    print(f"   -> Aprendendo sobre '{nome_ingrediente}' com a IA...")
    time.sleep(1)
    model = genai.GenerativeModel('models/gemini-flash-latest')
    contexto_taco = ", ".join(random.sample(lista_alimentos_taco, min(len(lista_alimentos_taco), 50)))
    prompt = f'Contexto: A Tabela TACO usa nomes como: "{contexto_taco}". Tarefa: Analise o ingrediente "{nome_ingrediente}". Responda com o nome da Tabela TACO que melhor corresponde. Se for irrelevante (tempero, água, marca) ou ambíguo, responda APENAS com "IGNORE". Responda apenas com o nome exato ou "IGNORE".'
    
    try:
        response = model.generate_content(prompt)
        nome_taco_sugerido = response.text.strip()
        insert_query = text("INSERT INTO mapeamento_cache (nome_ingrediente, nome_taco) VALUES (:nome_ing, :nome_taco) ON CONFLICT(nome_ingrediente) DO NOTHING")
        conn.execute(insert_query, {"nome_ing": nome_ingrediente, "nome_taco": nome_taco_sugerido})
        return nome_taco_sugerido if nome_taco_sugerido != 'IGNORE' else None
    except google_exceptions.ResourceExhausted as e:
        raise QuotaExceededError(f"Cota da API do Gemini excedida: {e}")
    except Exception as e:
        print(f"      -> Erro na API do Gemini durante o mapeamento: {e}")
        return None

def encontrar_alimento_localmente(nome_ingrediente: str, df_taco, cache_taco: set, conn, lista_alimentos_taco: list, api_disponivel: bool):
    if not nome_ingrediente: return None
    if nome_ingrediente in cache_taco: return True

    nome_normalizado = ''.join(c for c in unicodedata.normalize('NFD', nome_ingrediente.lower()) if unicodedata.category(c) != 'Mn')
    nome_mapeado = MAPEAMENTO_TACO_NORMALIZADO.get(nome_normalizado)
    nome_final_busca = ''.join(c for c in unicodedata.normalize('NFD', nome_mapeado.lower()) if unicodedata.category(c) != 'Mn') if nome_mapeado else nome_normalizado
    if nome_final_busca in df_taco.index: return True

    matches = difflib.get_close_matches(nome_final_busca, df_taco.index.tolist(), n=1, cutoff=0.8)
    if matches: return True

    if api_disponivel:
        nome_taco_aprendido = tentar_mapeamento_automatico_com_ia(nome_ingrediente, lista_alimentos_taco, conn)
        return bool(nome_taco_aprendido)
    
    return False

def auditar_banco_postgres():
    engine = None
    try:
        db_url = URL.create(
            drivername="postgresql+psycopg2",
            username=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"),
            host=os.getenv("POSTGRES_HOST"), port=os.getenv("POSTGRES_PORT"),
            database=os.getenv("POSTGRES_DB"), query={"client_encoding": "utf8"}
        )
        engine = create_engine(db_url)
        print("--- INICIANDO AUDITORIA DO BANCO POSTGRESQL (COM AUTOCORREÇÃO) ---")
        
        with engine.begin() as conn:
            criar_tabela_mapeamento_cache(conn)

            print("\n[ PARTE 1: STATUS GERAL DO PIPELINE ]")
            status_query = text("SELECT COUNT(*), COUNT(*) FILTER (WHERE processado_pela_llm = TRUE), COUNT(*) FILTER (WHERE nutrientes_calculados = TRUE) FROM receitas;")
            total_receitas, total_llm, total_calculado = conn.execute(status_query).fetchone()
            if total_receitas == 0: print("O banco de dados não contém nenhuma receita ainda."); return
            
            perc_llm = (total_llm / total_receitas) * 100
            perc_calculado = (total_calculado / total_receitas) * 100
            print(f"Total de Receitas no Banco: {total_receitas}")
            print(f"Receitas Estruturadas pela IA (LLM): {total_llm} ({perc_llm:.2f}%)")
            print(f"Receitas com Nutrientes Calculados: {total_calculado} ({perc_calculado:.2f}%)")
            
            print("\n[ PARTE 2: ANÁLISE DE QUALIDADE DOS CÁLCULOS ]")
            if total_calculado > 0:
                tabela_taco = carregar_tabela_taco()
                if tabela_taco is None: return
                cache_taco = carregar_cache_taco(conn)
                lista_alimentos_taco = tabela_taco['alimento'].tolist()

                receitas_query = text("SELECT id, titulo, ingredientes FROM receitas WHERE nutrientes_calculados = TRUE")
                receitas_calculadas = conn.execute(receitas_query).fetchall()
                total_a_auditar = len(receitas_calculadas)
                
                qualidade = {'excelente': [], 'bom': [], 'ruim': []}
                ingredientes_nao_encontrados_final = set()
                blacklist_pattern = r'\b(' + '|'.join(re.escape(term) for term in BLACKLISTA_IGNORAR) + r')\b'
                
                api_disponivel = True
                
                print(f"Auditando {total_a_auditar} receitas calculadas...")
                for i, (receita_id, titulo_quebrado, ingredientes_json) in enumerate(receitas_calculadas):
                    if not ingredientes_json: continue
                    ingredientes_relevantes, ingredientes_encontrados_count = 0, 0
                    for ingrediente in ingredientes_json:
                        nome = corrigir_texto_quebrado(ingrediente.get('nome_ingrediente'))
                        if not nome or re.search(blacklist_pattern, nome.lower()): continue
                        
                        ingredientes_relevantes += 1
                        try:
                            if encontrar_alimento_localmente(nome, tabela_taco, cache_taco, conn, lista_alimentos_taco, api_disponivel):
                                ingredientes_encontrados_count += 1
                            else:
                                ingredientes_nao_encontrados_final.add(nome)
                        except QuotaExceededError:
                            if api_disponivel:
                                print("\n\n!!! ATENÇÃO: Cota da API excedida. O mapeamento automático foi interrompido. !!!\n")
                            api_disponivel = False
                            ingredientes_nao_encontrados_final.add(nome)

                    taxa_acerto = (ingredientes_encontrados_count / ingredientes_relevantes * 100) if ingredientes_relevantes > 0 else 100.0
                    resultado = (corrigir_texto_quebrado(titulo_quebrado), f"{ingredientes_encontrados_count}/{ingredientes_relevantes} ({taxa_acerto:.1f}%)")
                    if taxa_acerto >= 90: qualidade['excelente'].append(resultado)
                    elif 70 <= taxa_acerto < 90: qualidade['bom'].append(resultado)
                    else: qualidade['ruim'].append(resultado)
                    
                    if (i + 1) % 200 == 0 and total_a_auditar > 200:
                        print(f"   ... {i + 1} de {total_a_auditar} receitas auditadas.")


                print(f"Qualidade Excelente (>= 90% dos ingredientes encontrados): {len(qualidade['excelente'])} receitas")
                print(f"Qualidade Boa (entre 70% e 90%): {len(qualidade['bom'])} receitas")
                print(f"Qualidade Ruim (< 70%): {len(qualidade['ruim'])} receitas")

                if qualidade['ruim'] or ingredientes_nao_encontrados_final:
                    print("\n[ PARTE 3: AMOSTRAGEM E PRÓXIMOS PASSOS ]")
                    if qualidade['ruim']:
                        amostra_titulo, amostra_stats = random.choice(qualidade['ruim'])
                        print(f"\nExemplo de Qualidade RUIM: '{amostra_titulo}' - (Ingredientes encontrados: {amostra_stats})")
                    if ingredientes_nao_encontrados_final:
                        print("\nIngredientes que a IA não conseguiu mapear ou ignorar:")
                        if not api_disponivel:
                            print("(A lista pode ser maior, pois o mapeamento automático foi interrompido pela cota da API)")
                        for item in sorted(list(ingredientes_nao_encontrados_final))[:15]:
                            print(f'   - "{item.lower()}"')
    except Exception as e:
        print(f"\nOcorreu um erro durante a auditoria: {e}")
        import traceback; traceback.print_exc()
    finally:
        if engine: engine.dispose()

if __name__ == "__main__":
    auditar_banco_postgres()