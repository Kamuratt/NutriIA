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

def corrigir_texto_quebrado(texto: str):
    if not isinstance(texto, str): return texto
    try: return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError): return texto

BLACKLISTA_IGNORAR = {'água', 'agua', 'sal', 'gelo', 'a gosto', 'quanto baste', 'q.b.'}
MAPEAMENTO_TACO = {"ovo": "Ovo, de galinha, inteiro, cru", "ovos": "Ovo, de galinha, inteiro, cru"}
MAPEAMENTO_TACO_NORMALIZADO = {''.join(c for c in unicodedata.normalize('NFD', k) if unicodedata.category(c) != 'Mn'): v for k, v in MAPEAMENTO_TACO.items()}

def carregar_tabela_taco(caminho_csv: str = "data/processed/tabela_taco_processada.csv"):
    try:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        caminho_completo = os.path.join(project_dir, caminho_csv)
        df = pd.read_csv(caminho_completo)
        df['alimento_normalizado'] = df['alimento'].astype(str).str.lower().apply(lambda x: ''.join(c for c in unicodedata.normalize('NFD', x) if unicodedata.category(c) != 'Mn'))
        df.set_index('alimento_normalizado', inplace=True)
        print("Tabela TACO carregada e normalizada com sucesso.")
        return df
    except Exception as e:
        print(f"ERRO ao carregar a Tabela TACO: {e}"); return None

def padronizar_unidade(unidade: str) -> str:
    if not unidade: return 'unidade'
    u_normalizada = ''.join(c for c in unicodedata.normalize('NFD', str(unidade).lower()) if unicodedata.category(c) != 'Mn')
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

def converter_para_gramas(ingrediente: dict) -> float:
    nome = ingrediente.get('nome_ingrediente')
    unidade = padronizar_unidade(ingrediente.get('unidade'))
    quantidade_str = str(ingrediente.get('quantidade', '0'))
    
    try:
        quantidade_str = quantidade_str.replace(',', '.').strip()
        total = 0.0
        if ' ' in quantidade_str:
            partes = quantidade_str.split(' ')
            for parte in partes:
                if '/' in parte:
                    num, den = map(float, parte.split('/'))
                    if den != 0: total += num / den
                elif parte:
                    total += float(parte)
        elif '/' in quantidade_str:
            num, den = map(float, quantidade_str.split('/'))
            if den != 0: total += num / den
        else:
            total = float(quantidade_str)
        quantidade = total
    except (ValueError, TypeError, ZeroDivisionError):
        return 0.0

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

def criar_tabela_cache(conn):
    query = text("""
        CREATE TABLE IF NOT EXISTS taco_complementar (
            alimento TEXT PRIMARY KEY, calorias REAL, proteina REAL, 
            lipideos REAL, carboidratos REAL, fibras REAL, texto_completo TEXT
        );
    """)
    conn.execute(query)
    print("Tabela de cache 'taco_complementar' garantida no PostgreSQL.")

def tentar_aprender_nutrientes_com_ia(nome_ingrediente: str) -> dict | None:
    print(f"   -> Aprendendo sobre '{nome_ingrediente}' com a IA...")
    time.sleep(1.1)
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f'Forneça a informação nutricional para 100 gramas de "{nome_ingrediente}". Responda APENAS com um único objeto JSON com as chaves "calorias", "proteina", "lipideos", "carboidratos", e "fibras". Se o ingrediente for inválido ou não tiver dados (ex: "água", "sal"), retorne um JSON com valores 0.'
    try:
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
        print(f"   -> IA aprendeu: '{nome_ingrediente}'")
        return nutrientes
    except google_exceptions.ResourceExhausted as e:
        raise QuotaExceededError(f"Cota da API do Gemini excedida: {e}")
    except Exception as e:
        print(f"      -> Erro na API do Gemini durante o aprendizado: {e}")
        return None

def encontrar_alimento(conn, nome_ingrediente: str, df_taco: pd.DataFrame, api_disponivel: bool):
    if not nome_ingrediente:
        return None

    cache_query = text("SELECT calorias, proteina, lipideos, carboidratos, fibras FROM taco_complementar WHERE alimento = :alimento")
    resultado_cache = conn.execute(cache_query, {"alimento": nome_ingrediente}).fetchone()
    if resultado_cache:
        return pd.Series(resultado_cache._asdict())

    nome_normalizado = ''.join(c for c in unicodedata.normalize('NFD', nome_ingrediente.lower()) if unicodedata.category(c) != 'Mn')
    nome_mapeado = MAPEAMENTO_TACO_NORMALIZADO.get(nome_normalizado)
    nome_final_busca = ''.join(c for c in unicodedata.normalize('NFD', nome_mapeado.lower()) if unicodedata.category(c) != 'Mn') if nome_mapeado else nome_normalizado
    if nome_final_busca in df_taco.index:
        return df_taco.loc[nome_final_busca]
    
    matches = difflib.get_close_matches(nome_final_busca, df_taco.index.tolist(), n=1, cutoff=0.8)
    if matches:
        return df_taco.loc[matches[0]]

    if api_disponivel:
        dados_aprendidos = tentar_aprender_nutrientes_com_ia(nome_ingrediente)
        if dados_aprendidos:
            insert_query = text("""
                INSERT INTO taco_complementar (alimento, calorias, proteina, lipideos, carboidratos, fibras, texto_completo)
                VALUES (:alimento, :calorias, :proteina, :lipideos, :carboidratos, :fibras, :texto_completo)
                ON CONFLICT(alimento) DO UPDATE SET
                    calorias = EXCLUDED.calorias, proteina = EXCLUDED.proteina, lipideos = EXCLUDED.lipideos,
                    carboidratos = EXCLUDED.carboidratos, fibras = EXCLUDED.fibras, texto_completo = EXCLUDED.texto_completo;
            """)
            conn.execute(insert_query, dados_aprendidos)
            dados_aprendidos.pop('alimento', None)
            dados_aprendidos.pop('texto_completo', None)
            return pd.Series(dados_aprendidos)
            
    return None

def salvar_nutrientes(conn, receita_id, totais):
    update_query = text("UPDATE receitas SET informacoes_nutricionais = :info, nutrientes_calculados = TRUE WHERE id = :id")
    conn.execute(update_query, {"info": json.dumps(totais), "id": receita_id})

if __name__ == "__main__":
    # Esta seção foi restaurada para que o script entenda --mode, --limit, etc.
    parser = argparse.ArgumentParser(description="Calcula os nutrientes de receitas no banco de dados NutriAI (PostgreSQL).")
    parser.add_argument('-m', '--mode', choices=['new', 'all', 'range'], default='new', help="Modo de execução: 'new' (padrão) para não calculadas, 'all' para todas, 'range' para IDs específicos.")
    parser.add_argument('-l', '--limit', type=int, help="Limita o número de receitas a processar.")
    parser.add_argument('ids', nargs='*', type=int, help="IDs ou intervalo de IDs para o modo 'range'. Ex: 10 20")
    args = parser.parse_args()

    df_taco = carregar_tabela_taco()
    if df_taco is None: exit()

    try:
        db_url = URL.create(drivername="postgresql+psycopg2", username=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST"), port=os.getenv("POSTGRES_PORT"), database=os.getenv("POSTGRES_DB"), query={"client_encoding": "utf8"})
        engine = create_engine(db_url)
        print("Conectado ao PostgreSQL.")
    except Exception as e:
        print(f"ERRO ao conectar ao PostgreSQL: {e}"); exit()
        
    api_disponivel = True
    
    receitas_para_calcular = []
    with engine.connect() as conn:
        criar_tabela_cache(conn)

        query_base = "SELECT id, titulo, ingredientes FROM receitas"
        params = {}
        where_clauses = ["processado_pela_llm = TRUE"]

        if args.mode == 'new':
            where_clauses.append("nutrientes_calculados = FALSE")
        elif args.mode == 'range':
            if not args.ids:
                print("ERRO: O modo 'range' requer um ou dois IDs."); exit()
            elif len(args.ids) == 1:
                where_clauses.append("id = :id_val")
                params["id_val"] = args.ids[0]
            else:
                start_id, end_id = sorted(args.ids)[:2]
                where_clauses.append("id BETWEEN :start_id AND :end_id")
                params.update({"start_id": start_id, "end_id": end_id})
        
        final_query_str = f"{query_base} WHERE {' AND '.join(where_clauses)} ORDER BY id"
        if args.limit:
            final_query_str += " LIMIT :limit_val"
            params["limit_val"] = args.limit
        
        receitas_para_calcular = conn.execute(text(final_query_str), params).fetchall()

    total_a_calcular = len(receitas_para_calcular)
    if not total_a_calcular:
        print("Nenhuma receita para calcular com os critérios fornecidos.")
    else:
        print(f"Encontradas {total_a_calcular} receitas para calcular os nutrientes. Iniciando...")

    for i, receita in enumerate(receitas_para_calcular):
        print(f"\n[{i+1}/{total_a_calcular}] Processando Receita ID {receita.id} ('{corrigir_texto_quebrado(receita.titulo)}')")
        
        with engine.begin() as conn:
            try:
                if not receita.ingredientes:
                    print("   -> AVISO: Receita sem ingredientes estruturados. Pulando.")
                    continue

                totais = {'calorias': 0.0, 'proteina': 0.0, 'lipideos': 0.0, 'carboidratos': 0.0, 'fibras': 0.0}
                sucesso_total = True

                for ing in receita.ingredientes:
                    nome_ing = corrigir_texto_quebrado(ing.get("nome_ingrediente"))
                    peso_g = converter_para_gramas(ing)
                    
                    if not nome_ing or peso_g <= 0:
                        continue
                        
                    if nome_ing.lower() in BLACKLISTA_IGNORAR:
                        continue
                        
                    dados_nutricionais = encontrar_alimento(conn, nome_ing, df_taco, api_disponivel)

                    if dados_nutricionais is not None and not dados_nutricionais.empty:
                        fator = peso_g / 100.0
                        for nutriente in totais.keys():
                            if nutriente in dados_nutricionais and pd.notna(dados_nutricionais[nutriente]):
                                totais[nutriente] += float(dados_nutricionais[nutriente]) * fator
                    else:
                        print(f"   -> AVISO: Falha ao encontrar/aprender sobre '{nome_ing}'. A receita não será calculada.")
                        sucesso_total = False
                        break 

                if sucesso_total:
                    salvar_nutrientes(conn, receita.id, totais)
                    print(f"   -> Nutrientes calculados e salvos.")

            except QuotaExceededError:
                api_disponivel = False
                print("\n\n!!! ATENÇÃO: Cota da API excedida. O aprendizado será desativado. !!!\n")
            except Exception as e_receita:
                print(f"   -> Erro inesperado ao processar a receita. Alterações desfeitas. Erro: {e_receita}")

    if engine: engine.dispose()
    print("\nProcesso de cálculo de nutrientes concluído.")