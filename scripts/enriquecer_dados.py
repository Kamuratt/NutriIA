# scripts/estruturacao_ingredientes.py
import json
import os
import time
import re
import argparse # Adicionado para argumentos de linha de comando
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# --- CONFIGURAÇÕES ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')

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

# --- FUNÇÕES DE PARSING E IA ---

def parse_ingrediente_com_regras(texto: str):
    """Tenta extrair dados de um ingrediente usando regras (RegEx)."""
    if not texto: return None
    unidades = ['xícara', 'xícaras', 'colher', 'colheres', 'copo', 'copos', 'g', 'kg', 'ml', 'l', 'lata', 'latas', 'dente', 'dentes', 'pitada', 'pitadas', 'unidade', 'unidades', 'fatia', 'fatias', 'ramo', 'ramos', 'folha', 'folhas', 'tablete', 'tabletes', 'pacote', 'pacotes', 'sachê', 'sachês']
    padrao = r"^\s*(?P<quantidade>[\d\./,\s]+|\w+)\s+(?P<unidade>" + "|".join(unidades) + r"(?:s)?(?: de chá| de sopa)?)\s*(?:de\s+)?(?P<resto>.*)"
    match = re.search(padrao, texto.strip(), re.IGNORECASE)
    if match:
        dados = match.groupdict()
        nome, *obs_list = re.split(r'[,(]', dados.get("resto", "").strip(), 1)
        observacao = obs_list[0].strip('() ') if obs_list else None
        return {"nome_ingrediente": nome.strip(), "quantidade": dados.get("quantidade").strip(), "unidade": dados.get("unidade").strip(), "observacao": observacao, "texto_original": texto}
    if "a gosto" in texto.lower() or "quanto baste" in texto.lower():
        nome_limpo = re.sub(r'a gosto|quanto baste', '', texto, flags=re.IGNORECASE).strip()
        return {"nome_ingrediente": nome_limpo, "quantidade": None, "unidade": None, "observacao": "a gosto", "texto_original": texto}
    return None

def analisar_ingrediente_com_gemini(texto_ingrediente: str):
    """Usa a IA para analisar e padronizar um ingrediente."""
    model = genai.GenerativeModel('models/gemini-flash-latest')
    # PROMPT MELHORADO
    prompt = f"""
    Analise o seguinte texto de ingrediente: '{texto_ingrediente}'.
    Extraia e retorne um único objeto JSON com as chaves: "nome_ingrediente", "quantidade", "unidade", "observacao".

    REGRAS IMPORTANTES:
    1. "nome_ingrediente": Deve ser o nome PADRONIZADO e CORRIGIDO do ingrediente principal. Exemplo: para "2 xicaras de farinha de trigo peneirada", o nome deve ser "farinha de trigo". Para "cebola picadinha", deve ser "cebola".
    2. "observacao": Deve conter os detalhes extras como "peneirada", "picadinha", "em rodelas".
    3. "quantidade": Deve ser um número ou fração em formato de string.
    4. "unidade": Deve ser a unidade de medida no singular (ex: "xícara", "colher de sopa").
    """
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
        )
        dados = json.loads(response.text)
        # Lógica robusta para lidar com respostas em lista
        if isinstance(dados, list):
            dados = dados[0] if dados else None
        if not isinstance(dados, dict):
            print(f"   -> Resposta da API para '{texto_ingrediente}' não é um objeto JSON válido: {dados}")
            return None
        dados['texto_original'] = texto_ingrediente
        return dados
    except google_exceptions.ResourceExhausted as e:
        raise QuotaExceededError(f"Cota da API do Gemini excedida: {e}")
    except Exception as e:
        print(f"   -> Erro na API do Gemini para '{texto_ingrediente}': {e}")
        return None

def corrigir_titulo_receita_com_gemini(titulo: str, retries=3, delay=2):
    """Usa a IA para corrigir e padronizar o título de uma receita."""
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"Corrija e padronize o seguinte título de receita: '{titulo}'. Remova erros de digitação e formatações estranhas. Retorne APENAS o texto do título corrigido, sem aspas ou palavras como 'Título:'."
    for attempt in range(retries):
        try:
            response = model.generate_content(prompt)
            titulo_corrigido = response.text.strip().strip('"').strip("'")
            if titulo_corrigido:
                return titulo_corrigido
        except Exception as e:
            print(f"   -> Aviso: Erro ao tentar corrigir o título '{titulo}' (tentativa {attempt + 1}): {e}")
            time.sleep(delay)
    print(f"   -> Aviso: Não foi possível corrigir o título '{titulo}'. Usando o original.")
    return titulo

# --- FUNÇÕES DE BANCO DE DADOS ---

def buscar_receitas_nao_processadas(conn, limit=None):
    """Busca receitas que ainda não foram processadas pela IA."""
    query_str = "SELECT id, titulo, ingredientes_brutos FROM receitas WHERE processado_pela_llm = FALSE AND ingredientes_brutos IS NOT NULL ORDER BY id;"
    if limit:
        query_str = query_str.replace(";", f" LIMIT {limit};")
        
    query = text(query_str)
    result = conn.execute(query).fetchall()
    return result

def salvar_dados_e_marcar_como_processada(conn, receita_id, titulo_corrigido, lista_ingredientes_estruturados):
    """Salva os dados processados e o título corrigido no banco."""
    update_query = text("""
        UPDATE receitas SET
            titulo = :titulo,
            ingredientes = :ingredientes_json,
            processado_pela_llm = TRUE
        WHERE id = :receita_id;
    """)
    params = {
        "titulo": titulo_corrigido,
        "ingredientes_json": json.dumps(lista_ingredientes_estruturados, ensure_ascii=False),
        "receita_id": receita_id
    }
    conn.execute(update_query, params)

# --- FLUXO PRINCIPAL ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Processa ingredientes de novas receitas usando IA.")
    parser.add_argument("--limit", type=int, help="Número máximo de receitas para processar.")
    args = parser.parse_args()

    try:
        db_url = URL.create(
            drivername="postgresql+psycopg2", username=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST"),
            port=os.getenv("POSTGRES_PORT"), database=os.getenv("POSTGRES_DB"),
            query={"client_encoding": "utf8"}
        )
        engine = create_engine(db_url)
        print("✔️ Conectado ao PostgreSQL.")
    except Exception as e:
        print(f"❌ ERRO ao conectar ao PostgreSQL: {e}")
        exit()

    api_calls_count = 0
    
    try:
        with engine.connect() as conn:
            receitas_para_processar = buscar_receitas_nao_processadas(conn, limit=args.limit)
        
        total_receitas = len(receitas_para_processar)
        if not receitas_para_processar:
            print("Nenhuma receita nova para processar.")
        else:
            print(f"Encontradas {total_receitas} receitas para processar com IA.")

        print("\nIniciando processamento das receitas...")
        
        for i, row in enumerate(receitas_para_processar):
            receita_id, titulo_bruto, ingredientes_brutos = row
            
            with engine.begin() as conn:
                try:
                    # 1. Corrigir Título
                    try:
                        titulo_corrigido_encoding = titulo_bruto.encode('latin1').decode('utf-8')
                    except:
                        titulo_corrigido_encoding = titulo_bruto
                    
                    titulo_final = corrigir_titulo_receita_com_gemini(titulo_corrigido_encoding)
                    api_calls_count += 1
                    time.sleep(1.1)

                    if not ingredientes_brutos:
                        salvar_dados_e_marcar_como_processada(conn, receita_id, titulo_final, [])
                        continue
                    
                    # 2. Processar Ingredientes
                    lista_ingredientes_estruturados = []
                    sucesso_total_receita = True
                    
                    for texto_ingrediente in ingredientes_brutos:
                        dados_estruturados = parse_ingrediente_com_regras(texto_ingrediente)
                        
                        if not dados_estruturados:
                            dados_estruturados = analisar_ingrediente_com_gemini(texto_ingrediente)
                            api_calls_count += 1
                            time.sleep(1.1)

                        if dados_estruturados:
                            lista_ingredientes_estruturados.append(dados_estruturados)
                        else:
                            print(f"\nFalha ao processar ingrediente '{texto_ingrediente}' para a receita ID {receita_id}.")
                            sucesso_total_receita = False
                            break
                    
                    # 3. Salvar no Banco
                    if sucesso_total_receita:
                        salvar_dados_e_marcar_como_processada(conn, receita_id, titulo_final, lista_ingredientes_estruturados)
                        print(f"   -> ✅ Receita ID {receita_id} ('{titulo_final}') foi processada e salva.")
                
                except Exception as e_receita:
                    print(f"\n❌ Erro ao processar a receita ID {receita_id}. Alterações desfeitas. Erro: {e_receita}")

            if (i + 1) % 50 == 0 and total_receitas > 50:
                print(f"\n--- Progresso: {i + 1} de {total_receitas} receitas processadas. ---")

    except QuotaExceededError:
        print(f"\n!!! ATENÇÃO: Cota da API do Gemini excedida. !!!")
        print(f"O script fez {api_calls_count} chamadas à IA antes de parar.")
        print("Na próxima execução, ele continuará de onde parou.")
    except Exception as e_geral:
        print(f"\nUm erro geral ocorreu: {e_geral}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nProcesso de estruturação de ingredientes concluído.")