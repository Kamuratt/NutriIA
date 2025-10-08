# scripts/calcular_nutrientes.py
import pandas as pd
import unicodedata
import random
import difflib
import re
import os
import time
import argparse
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
    print("API do Google Gemini configurada.")
except ValueError as e:
    print(f"ERRO DE CONFIGURAÇÃO DA API: {e}"); exit()

# --- Funções e Constantes ---
def corrigir_texto_quebrado(texto: str):
    if not texto: return texto
    try: return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError): return texto

BLACKLISTA_IGNORAR = {
    'água', 'agua', 'sal', 'gelo', 'palito de dente', 'papel chumbo', 'receita de', 'a gosto', 'quanto baste', 'q.b.', 'fritadeira elétrica',
    'cravo-da-índia', 'ervas finas', 'pimenta biquinho', 'cravo', 'água morna', 'açúcar ou adoçante', 'becel amanteigado', 'becel', 
    'canela em pau', 'doritos grande', 'essência de baunilha', 'folhas de hortelã', 'frutas (morango, uva ou pessego)', 'garam masala'
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
        print("✔️ Tabela TACO carregada e normalizada com sucesso.")
        return df
    except Exception as e:
        print(f"❌ ERRO ao carregar a Tabela TACO: {e}"); return None

def padronizar_unidade(unidade: str) -> str:
    if not unidade: return 'unidade'
    u_normalizada = ''.join(c for c in unicodedata.normalize('NFD', unidade.lower()) if unicodedata.category(c) != 'Mn')
    u_limpa = u_normalizada.replace('(', '').replace(')', '').strip()
    mapeamento = {
        'xicara': 'xicara', 'xicaras': 'xicara', 'xicara de cha': 'xicara', 'xicara cha': 'xicara', 'xicaras de cha': 'xicara',
        'colher de sopa': 'colher de sopa', 'colheres de sopa': 'colher de sopa', 'colher sopa': 'colher de sopa', 'sopa': 'colher de sopa', 'colher': 'colher de sopa', 'colheres': 'colher de sopa',
        'colher de cha': 'colher de cha', 'colheres de cha': 'colher de cha', 'colher cha': 'colher de cha', 'colher de sobremesa': 'colher de sobremesa', 'colher de cafe': 'colher de cafe', 'colher cafe': 'colher de cafe', 'colherzinha': 'colher de cha', 'colhercha': 'colher de cha',
        'dente': 'dente', 'dentes': 'dente', 'copo': 'copo', 'copos': 'copo', 'lata': 'lata', 'pacote': 'pacote',
        'grama': 'g', 'gramas': 'g', 'quilo': 'kg', 'quilos': 'kg', 'litro': 'l', 'litros': 'l', 'pitada': 'pitada',
        'unidade': 'unidade', 'unidades': 'unidade', 'fatia': 'fatia', 'fatias': 'fatia', 'sache': 'sache',
        'tablete': 'tablete', 'banda': 'banda', 'pedaco': 'pedaço', 'pote': 'pote', 'cabeça': 'cabeça', 'cabecas': 'cabeça',
        'cubo': 'cubo', 'cubos': 'cubo', 'folhas': 'unidade', 'folha': 'unidade', 'graos': 'unidade', 'polpa': 'unidade',
        'pires': 'pires', 'receita': 'receita', 'limao': 'unidade', 'medida': 'medida', 'gotas': 'gotas', 'bombons': 'unidade', 'bolas': 'bola',
        'rama': 'unidade'
    }
    return mapeamento.get(u_limpa, u_limpa)

CONVERSOES_PARA_GRAMAS = {
    ('genérico', 'xicara'): 240.0, ('genérico', 'copo'): 200.0, ('genérico', 'colher de sopa'): 15.0, ('genérico', 'colher de sobremesa'): 10.0, ('genérico', 'colher de cha'): 5.0, ('genérico', 'colher de cafe'): 2.5,
    ('açúcar', 'xicara'): 160.0, ('farinha de trigo', 'xicara'): 120.0, ('manteiga', 'colher de sopa'): 15.0, ('queijo ralado', 'colher de sopa'): 6.0,
    ('genérico', 'unidade'): 100.0, ('ovo', 'unidade'): 50.0, ('gema', 'unidade'): 20.0, ('cebola', 'unidade'): 120.0, ('limão', 'unidade'): 80.0,
    ('tomate', 'unidade'): 90.0, ('banana', 'unidade'): 100.0, ('arroz', 'xicara'): 185.0,
}
CONVERSOES_PARA_GRAMAS_NORMALIZADO = {(''.join(c for c in unicodedata.normalize('NFD', k[0]) if unicodedata.category(c) != 'Mn'), k[1]): v for k, v in CONVERSOES_PARA_GRAMAS.items()}

def converter_para_gramas(ingrediente: dict):
    nome = ingrediente.get('nome_ingrediente')
    unidade = padronizar_unidade(ingrediente.get('unidade'))
    quantidade = ingrediente.get('quantidade')
    if quantidade is None: return 0.0
    try:
        if isinstance(quantidade, str):
            partes = quantidade.split()
            total = 0
            for parte in partes:
                if '/' in parte:
                    num, den = parte.split('/')
                    total += float(num) / float(den)
                else:
                    total += float(parte)
            quantidade = total
        else:
            quantidade = float(quantidade)
    except (ValueError, TypeError): return 0.0
    if unidade in ['g', 'gramas']: return quantidade
    if unidade in ['kg', 'quilos']: return quantidade * 1000
    if unidade in ['ml']: return quantidade
    if unidade in ['l', 'litros']: return quantidade * 1000
    if nome and unidade:
        nome_normalizado = ''.join(c for c in unicodedata.normalize('NFD', nome.lower()) if unicodedata.category(c) != 'Mn')
        peso = CONVERSOES_PARA_GRAMAS_NORMALIZADO.get((nome_normalizado, unidade))
        if peso is not None: return quantidade * peso
        peso = CONVERSOES_PARA_GRAMAS_NORMALIZADO.get(('genérico', unidade))
        if peso is not None: return quantidade * peso
    return 0.0

def criar_tabelas_de_cache(conn):
    conn.execute(text("CREATE TABLE IF NOT EXISTS taco_complementar (alimento TEXT PRIMARY KEY, calorias REAL, proteina REAL, lipideos REAL, carboidratos REAL, fibras REAL);"))
    conn.execute(text("CREATE TABLE IF NOT EXISTS mapeamento_cache (nome_ingrediente TEXT PRIMARY KEY, nome_taco TEXT);"))
    print("✔️ Tabelas de cache ('taco_complementar', 'mapeamento_cache') garantidas no PostgreSQL.")

def tentar_mapeamento_automatico_com_ia(nome_ingrediente: str, lista_alimentos_taco: list, conn):
    cache_query = text("SELECT nome_taco FROM mapeamento_cache WHERE nome_ingrediente = :nome_ing")
    resultado = conn.execute(cache_query, {"nome_ing": nome_ingrediente}).fetchone()
    if resultado: return resultado[0] if resultado[0] != 'IGNORE' else None

    print(f"   -> Aprendendo sobre '{nome_ingrediente}' com a IA...")
    time.sleep(1.1)
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
        print(f"      -> Erro na API do Gemini durante o mapeamento: {e}"); return None

def encontrar_alimento_na_taco(nome_ingrediente: str, df_taco, conn, lista_alimentos_taco: list, api_disponivel: bool):
    if not nome_ingrediente: return None
    cache_query = text("SELECT calorias, proteina, lipideos, carboidratos, fibras FROM taco_complementar WHERE alimento = :alimento")
    resultado_cache = conn.execute(cache_query, {"alimento": nome_ingrediente}).fetchone()
    if resultado_cache: return pd.Series(resultado_cache._asdict())
    
    nome_normalizado = ''.join(c for c in unicodedata.normalize('NFD', nome_ingrediente.lower()) if unicodedata.category(c) != 'Mn')
    nome_mapeado = MAPEAMENTO_TACO_NORMALIZADO.get(nome_normalizado)
    nome_final_busca = ''.join(c for c in unicodedata.normalize('NFD', nome_mapeado.lower()) if unicodedata.category(c) != 'Mn') if nome_mapeado else nome_normalizado
    if nome_final_busca in df_taco.index: return df_taco.loc[nome_final_busca]
    
    matches = difflib.get_close_matches(nome_final_busca, df_taco.index.tolist(), n=1, cutoff=0.8)
    if matches: return df_taco.loc[matches[0]]
    
    if api_disponivel:
        nome_taco_aprendido = tentar_mapeamento_automatico_com_ia(nome_ingrediente, lista_alimentos_taco, conn)
        if nome_taco_aprendido:
            nome_aprendido_normalizado = ''.join(c for c in unicodedata.normalize('NFD', nome_taco_aprendido.lower()) if unicodedata.category(c) != 'Mn')
            if nome_aprendido_normalizado in df_taco.index:
                return df_taco.loc[nome_aprendido_normalizado]
    return None

def calcular_nutrientes_receita(ingredientes: list, df_taco, conn, lista_alimentos_taco, api_disponivel):
    if not ingredientes: return None, True
    totais = {'calorias': 0.0, 'proteina': 0.0, 'lipideos': 0.0, 'carboidratos': 0.0, 'fibras': 0.0}
    blacklist_pattern = r'\b(' + '|'.join(re.escape(term) for term in BLACKLISTA_IGNORAR) + r')\b'
    
    for ing in ingredientes:
        nome_quebrado = ing.get('nome_ingrediente')
        nome_ingrediente = corrigir_texto_quebrado(nome_quebrado)
        if not nome_ingrediente or re.search(blacklist_pattern, nome_ingrediente.lower()): continue
        
        peso_em_gramas = converter_para_gramas(ing)
        if peso_em_gramas > 0:
            dados_taco = encontrar_alimento_na_taco(nome_ingrediente, df_taco, conn, lista_alimentos_taco, api_disponivel)
            if dados_taco is not None and not dados_taco.empty:
                fator = peso_em_gramas / 100.0
                for nutriente in totais.keys():
                    if nutriente in dados_taco and pd.notna(dados_taco[nutriente]):
                        try: totais[nutriente] += float(dados_taco[nutriente]) * fator
                        except (ValueError, TypeError): continue
            else:
                print(f"     -> AVISO: Não foram encontrados dados para '{nome_ingrediente}'. A receita não será calculada.")
                return None, False
    return totais, True

def salvar_nutrientes_no_banco(receita_id: int, totais: dict, conn):
    query = text("UPDATE receitas SET informacoes_nutricionais = :info_nutri, nutrientes_calculados = TRUE WHERE id = :receita_id;")
    params = { "receita_id": receita_id, "info_nutri": json.dumps(totais) }
    conn.execute(query, params)

# --- BLOCO PRINCIPAL ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calcula os nutrientes de receitas no banco de dados NutriAI (PostgreSQL).")
    parser.add_argument('-m', '--mode', choices=['new', 'all', 'range'], default='new', help="Modo de execução.")
    parser.add_argument('-l', '--limit', type=int, default=None, help="Limita o número de receitas a processar.")
    parser.add_argument('ids', nargs='*', type=int, help="IDs ou intervalo para o modo 'range'.")
    args = parser.parse_args()

    tabela_taco_df = carregar_tabela_taco()
    if tabela_taco_df is None: exit()

    try:
        db_url = URL.create(
            drivername="postgresql+psycopg2",
            username=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"),
            host=os.getenv("POSTGRES_HOST"), port=os.getenv("POSTGRES_PORT"),
            database=os.getenv("POSTGRES_DB"), query={"client_encoding": "utf8"}
        )
        engine = create_engine(db_url)
        print("✔️ Conectado ao PostgreSQL.")
    except Exception as e:
        print(f"❌ ERRO ao conectar ao PostgreSQL: {e}"); exit()

    try:
        with engine.begin() as conn:
            criar_tabelas_de_cache(conn)
            lista_alimentos_taco = tabela_taco_df['alimento'].tolist()

            query_base = "SELECT id, titulo, ingredientes FROM receitas"
            params = {}
            where_clauses = []
            if args.mode == 'all': where_clauses.append("processado_pela_llm = TRUE")
            elif args.mode == 'new': where_clauses.append("processado_pela_llm = TRUE AND nutrientes_calculados = FALSE")
            elif args.mode == 'range':
                if not args.ids: print("ERRO: O modo 'range' requer IDs."); exit()
                elif len(args.ids) == 1: where_clauses.append("id = :id_val"); params["id_val"] = args.ids[0]
                else:
                    start_id, end_id = sorted(args.ids)[:2]
                    where_clauses.append("id BETWEEN :start_id AND :end_id")
                    params.update({"start_id": start_id, "end_id": end_id})
            
            final_query_str = query_base
            if where_clauses: final_query_str += " WHERE " + " AND ".join(where_clauses)
            if args.limit: final_query_str += " LIMIT :limit_val"; params["limit_val"] = args.limit
            
            receitas_para_calcular = conn.execute(text(final_query_str), params).fetchall()
            total_a_calcular = len(receitas_para_calcular)
            
            if not receitas_para_calcular:
                print("\nNenhuma receita para calcular com os critérios fornecidos.")
            else:
                print(f"\nEncontradas {total_a_calcular} receitas para calcular os nutrientes.")
                print("Iniciando cálculo...")
            
            api_disponivel = True
            
            # Removido TQDM e simplificado o loop
            for i, receita in enumerate(receitas_para_calcular):
                try:
                    totais_nutricionais, sucesso = calcular_nutrientes_receita(receita.ingredientes, tabela_taco_df, conn, lista_alimentos_taco, api_disponivel)
                    if sucesso and totais_nutricionais is not None:
                        salvar_nutrientes_no_banco(receita.id, totais_nutricionais, conn)
                        print(f"  -> ✅ Nutrientes da Receita ID {receita.id} ('{corrigir_texto_quebrado(receita.titulo)}') foram calculados e salvos.")
                except QuotaExceededError:
                    if api_disponivel: print("\n\n!!! ATENÇÃO: Cota da API excedida. O mapeamento automático foi interrompido. !!!\n")
                    api_disponivel = False
                
                if (i + 1) % 100 == 0 and total_a_calcular > 100:
                    restantes = total_a_calcular - (i + 1)
                    print(f"\n--- Progresso: {i + 1} de {total_a_calcular} receitas calculadas. Faltam {restantes}. ---\n")

    except Exception as e_geral:
        print(f"❌ Ocorreu um erro geral e o script PAROU: {e_geral}")
        import traceback; traceback.print_exc()
    finally:
        print("\nProcesso de cálculo de nutrientes concluído.")