# scripts/auditoria_dados.py
import pandas as pd
import unicodedata
import json
import os
import time
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from dotenv import load_dotenv

# --- CONFIGURAÇÃO (sem alterações) ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')
class QuotaExceededError(Exception): pass
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: raise ValueError("Chave de API do Google não encontrada.")
    genai.configure(api_key=api_key)
    print("API do Google Gemini configurada.")
except ValueError as e:
    print(f"ERRO DE CONFIGURAÇÃO DA API: {e}"); exit()

# --- FUNÇÕES AUXILIARES (sem alterações) ---
def corrigir_texto_quebrado(texto: str):
    if not isinstance(texto, str): return texto
    try: return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError): return texto

def normalizar_texto(texto: str):
    if not texto: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', texto.lower()) if unicodedata.category(c) != 'Mn')

# --- FUNÇÕES DE BANCO E IA (com a lógica de limpeza) ---

def carregar_alimentos_conhecidos(engine: Engine) -> set:
    conhecidos = set()
    try:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        caminho_taco = os.path.join(project_dir, "data/processed/tabela_taco_processada.csv")
        df_taco = pd.read_csv(caminho_taco)
        for alimento in df_taco['alimento']:
            conhecidos.add(normalizar_texto(alimento))
        print(f"✔️ Carregados {len(conhecidos)} alimentos da Tabela TACO.")
        with engine.connect() as conn:
            resultado = conn.execute(text("SELECT alimento FROM taco_complementar;")).fetchall()
            for row in resultado:
                conhecidos.add(normalizar_texto(corrigir_texto_quebrado(row[0])))
        print(f"✔️ Total de {len(conhecidos)} alimentos conhecidos (TACO + Cache).")
        return conhecidos
    except Exception as e:
        print(f"❌ AVISO: Não foi possível carregar todos os alimentos conhecidos: {e}")
        return conhecidos

def criar_e_carregar_mapa_de_correcoes(conn) -> dict:
    conn.execute(text("CREATE TABLE IF NOT EXISTS mapeamento_correcoes (nome_incorreto TEXT PRIMARY KEY, nome_corrigido TEXT);"))
    resultado = conn.execute(text("SELECT nome_incorreto, nome_corrigido FROM mapeamento_correcoes;")).fetchall()
    return {row[0]: row[1] for row in resultado}

def obter_ingredientes_unicos_das_receitas(conn) -> set:
    print("Buscando todos os nomes de ingredientes únicos das receitas...")
    query = text("SELECT DISTINCT jsonb_array_elements(ingredientes)->>'nome_ingrediente' as nome FROM receitas WHERE ingredientes IS NOT NULL;")
    resultado = conn.execute(query).fetchall()
    ingredientes_unicos = {corrigir_texto_quebrado(row[0]) for row in resultado if row[0]}
    print(f"Encontrados {len(ingredientes_unicos)} nomes de ingredientes únicos.")
    return ingredientes_unicos

def corrigir_ingredientes_com_ia(lista_ingredientes: list) -> dict:
    if not lista_ingredientes: return {}
    print(f"   -> Enviando lote de {len(lista_ingredientes)} ingredientes para correção da IA...")
    time.sleep(1.1)
    model = genai.GenerativeModel('models/gemini-flash-latest')
    lista_formatada = "\n".join([f'- "{item}"' for item in lista_ingredientes])
    prompt = f"""
    Analise a seguinte lista de nomes de ingredientes de receitas. Sua tarefa é padronizar cada um para seu nome base. Se um item claramente não for um ingrediente (ex: "Modo de Preparo", "Forma untada", "IGNORE, óleo"), mapeie para a palavra "IGNORE".
    Lista de Ingredientes:
    {lista_formatada}
    Responda APENAS com um único objeto JSON onde a chave é o nome original da lista e o valor é o nome corrigido/padronizado ou "IGNORE".
    Exemplo: {{"fuba": "fubá", "ovos caipira": "ovo", "Formas": "IGNORE"}}
    """
    try:
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        correcoes = json.loads(response.text)
        print(f"   -> ✅ IA retornou {len(correcoes)} correções.")
        return correcoes
    except google_exceptions.ResourceExhausted as e:
        raise QuotaExceededError(f"Cota da API do Gemini excedida: {e}")
    except Exception as e:
        print(f"      -> Erro na API do Gemini durante a correção em lote: {e}")
        return {}

def salvar_correcoes_no_banco(conn, novas_correcoes: dict) -> int:
    if not novas_correcoes: return 0
    insert_query = text("INSERT INTO mapeamento_correcoes (nome_incorreto, nome_corrigido) VALUES (:incorreto, :corrigido) ON CONFLICT(nome_incorreto) DO NOTHING;")
    parametros = [{"incorreto": k, "corrigido": v} for k, v in novas_correcoes.items()]
    resultado = conn.execute(insert_query, parametros)
    return resultado.rowcount

def aplicar_correcoes_e_limpeza(engine: Engine, mapa_de_correcoes: dict) -> int:
    """
    NOVA LÓGICA: Varre as receitas, corrige os nomes E REMOVE os ingredientes marcados como "IGNORE".
    """
    print("\nIniciando aplicação de correções e limpeza nas receitas...")
    
    with engine.connect() as conn:
        receitas = conn.execute(text("SELECT id, ingredientes FROM receitas WHERE ingredientes IS NOT NULL;")).fetchall()

    receitas_modificadas = 0
    for i, (receita_id, ingredientes_json) in enumerate(receitas):
        if (i + 1) % 500 == 0:
            print(f"   ... {i+1} de {len(receitas)} receitas verificadas.")

        ingredientes_finais = []
        modificado = False
        
        for ing in ingredientes_json:
            nome_original = corrigir_texto_quebrado(ing.get("nome_ingrediente"))

            # Verifica se o ingrediente original deve ser ignorado
            if mapa_de_correcoes.get(nome_original) == "IGNORE":
                modificado = True
                continue # PULA este ingrediente, não o adiciona à lista final

            # Se não for ignorado, verifica se precisa de correção de nome
            if nome_original in mapa_de_correcoes:
                nome_corrigido = mapa_de_correcoes[nome_original]
                if nome_corrigido != nome_original:
                    ing['nome_ingrediente'] = nome_corrigido
                    modificado = True
            
            ingredientes_finais.append(ing)

        if modificado:
            with engine.begin() as conn:
                update_query = text("UPDATE receitas SET ingredientes = :ingredientes_json WHERE id = :id;")
                conn.execute(update_query, {"ingredientes_json": json.dumps(ingredientes_finais, ensure_ascii=False), "id": receita_id})
            receitas_modificadas += 1
            
    print(f"✅ Limpeza e correções aplicadas! {receitas_modificadas} receitas foram atualizadas.")
    return receitas_modificadas

def gerar_relatorio_final(engine: Engine, stats: dict):
    # (Função de relatório sem alterações)
    print("\n\n" + "="*80)
    print("= RELATÓRIO FINAL DE AUDITORIA E QUALIDADE DE DADOS".center(80))
    print("="*80)
    with engine.connect() as conn:
        print("\n--- [1. VISÃO GERAL DO ECOSSISTEMA] ---")
        total, llm, calc = conn.execute(text("SELECT COUNT(*), COUNT(*) FILTER (WHERE processado_pela_llm), COUNT(*) FILTER (WHERE nutrientes_calculados) FROM receitas;")).fetchone()
        print(f"Total de Receitas no Banco de Dados: {total}")
        print(f"  - Receitas com Ingredientes Estruturados: {llm} ({llm/total:.1%})")
        print(f"  - Receitas com Nutrientes Calculados:   {calc} ({calc/total:.1%})")
        print("\n--- [2. DIAGNÓSTICO DE QUALIDADE (ANTES DA EXECUÇÃO)] ---")
        total_unicos = stats['total_ingredientes_unicos']
        conhecidos = stats['ingredientes_ja_conhecidos']
        suspeitos = total_unicos - conhecidos
        print(f"Total de Nomes de Ingredientes Únicos: {total_unicos}")
        print(f"  - Nomes Já Conhecidos (TACO/Cache):    {conhecidos}")
        print(f"  - Nomes Suspeitos (enviados à IA):     {suspeitos}")
        print("\n--- [3. RESUMO DA EXECUÇÃO ATUAL] ---")
        total_correcoes_banco = conn.execute(text("SELECT COUNT(*) FROM mapeamento_correcoes;")).scalar_one()
        print(f"Novas Correções/Ignorados Aprendidos com a IA: {stats['correcoes_aprendidas_nesta_execucao']}")
        print(f"Receitas Modificadas (Nomes Corrigidos ou Lixo Removido): {stats['receitas_modificadas']}")
        print(f"Total de Regras na Base de Conhecimento: {total_correcoes_banco}")
        print("\n--- [4. PONTOS DE MELHORIA E PRÓXIMOS PASSOS] ---")
        ignorados = conn.execute(text("SELECT nome_incorreto FROM mapeamento_correcoes WHERE nome_corrigido = 'IGNORE' ORDER BY nome_incorreto LIMIT 20;")).fetchall()
        if ignorados:
            print("Itens que foram aprendidos como 'IGNORE' e removidos das receitas:")
            for item in ignorados:
                print(f"  - \"{item[0]}\"")
        print("\n[!] AÇÃO RECOMENDADA:")
        print("    1. A base de dados foi limpa. Ingredientes inválidos foram removidos.")
        print("    2. Rode o script 'calcular_nutrientes.py' para preencher os dados das receitas.")
        print("    3. Melhore o prompt do script 'estruturacao_ingredientes.py' (conforme sugerido)")
        print("       para evitar a criação de novos ingredientes inválidos no futuro.")
    print("\n" + "="*80)

# --- BLOCO PRINCIPAL (com a nova função de limpeza) ---
if __name__ == "__main__":
    try:
        db_url = URL.create(drivername="postgresql+psycopg2", username=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST"), port=os.getenv("POSTGRES_PORT"), database=os.getenv("POSTGRES_DB"), query={"client_encoding": "utf8"})
        engine = create_engine(db_url)
        print("✔️ Conectado ao PostgreSQL.")
    except Exception as e:
        print(f"❌ ERRO ao conectar ao PostgreSQL: {e}"); exit()

    stats = {
        "total_ingredientes_unicos": 0,
        "ingredientes_ja_conhecidos": 0,
        "correcoes_aprendidas_nesta_execucao": 0,
        "receitas_modificadas": 0
    }
    try:
        print("\n--- [PARTE 1: Aprendendo e Salvando Correções] ---")
        alimentos_conhecidos_normalizados = carregar_alimentos_conhecidos(engine)
        
        with engine.begin() as conn:
            mapa_de_correcoes = criar_e_carregar_mapa_de_correcoes(conn)
            ingredientes_unicos = obter_ingredientes_unicos_das_receitas(conn)
            stats['total_ingredientes_unicos'] = len(ingredientes_unicos)
            ingredientes_a_corrigir = []
            for ing in ingredientes_unicos:
                if ing in mapa_de_correcoes: continue
                if normalizar_texto(ing) in alimentos_conhecidos_normalizados:
                    stats['ingredientes_ja_conhecidos'] += 1
                    continue
                ingredientes_a_corrigir.append(ing)
            print(f"Encontrados {len(ingredientes_a_corrigir)} ingredientes que precisam de verificação da IA.")
            lote_size = 50
            for i in range(0, len(ingredientes_a_corrigir), lote_size):
                lote = ingredientes_a_corrigir[i:i + lote_size]
                novas_correcoes = corrigir_ingredientes_com_ia(lote)
                salvos = salvar_correcoes_no_banco(conn, novas_correcoes)
                stats['correcoes_aprendidas_nesta_execucao'] += salvos
                mapa_de_correcoes.update(novas_correcoes)

        print("\n--- [PARTE 2: Aplicando Correções e Limpeza nas Receitas] ---")
        with engine.connect() as conn:
            mapa_completo = criar_e_carregar_mapa_de_correcoes(conn)
        
        stats['receitas_modificadas'] = aplicar_correcoes_e_limpeza(engine, mapa_completo)

    except QuotaExceededError as e:
        print(f"\n!!! ATENÇÃO: Cota da API excedida. O processo de aprendizado parou. !!!")
    except Exception as e:
        print(f"\nOcorreu um erro geral durante a auditoria: {e}")
        import traceback; traceback.print_exc()
    finally:
        if engine:
            gerar_relatorio_final(engine, stats)
            engine.dispose()
        print("\nProcesso de auditoria e correção concluído.")