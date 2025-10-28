import json
import os
import time
import re
import argparse
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

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
    
    # Adicionada a regra crítica para retornar "IGNORE" caso não seja um ingrediente.
    prompt = f"""
    Analise o seguinte texto: '{texto_ingrediente}'.

    REGRAS CRÍTICAS:
    1. Se o texto NÃO for um ingrediente real (ex: um subtítulo como "Massa", "Recheio"; um utensílio como "Forma untada"; uma instrução), retorne APENAS a palavra "IGNORE".
    2. Se o texto FOR um ingrediente real, extraia e retorne um único objeto JSON com as chaves: "nome_ingrediente", "quantidade", "unidade", "observacao".

    REGRAS DE EXTRAÇÃO:
    - "nome_ingrediente": O nome PADRONIZADO do ingrediente principal. Ex: para "cebola picadinha", o nome é "cebola".
    - "observacao": Detalhes extras como "picadinha", "peneirada", "em rodelas".
    - "unidade": Padronize para o singular (ex: "xícara", não "xícaras").

    Exemplos de Resposta:
    - Para o texto "2 xicaras de farinha de trigo peneirada", retorne: {{"nome_ingrediente": "farinha de trigo", "quantidade": "2", "unidade": "xícara", "observacao": "peneirada"}}
    - Para o texto "Cobertura:", retorne: IGNORE
    - Para o texto "Forma de 20cm untada", retorne: IGNORE
    """
    
    try:
        # Removido o response_mime_type para a IA ter liberdade de responder "IGNORE" como texto
        response = model.generate_content(prompt)
        
        texto_resposta = response.text.strip()
        
        # Verifica se a IA decidiu ignorar o texto
        if texto_resposta == "IGNORE":
            print(f"   -> IA ignorou texto que não é ingrediente: '{texto_ingrediente}'")
            return "IGNORE" # Retorna a flag para ser tratada no loop principal

        # Se não for "IGNORE", tenta processar como JSON
        dados = json.loads(texto_resposta)
        if not isinstance(dados, dict):
            print(f"   -> Resposta da API para '{texto_ingrediente}' não é um objeto JSON válido: {dados}")
            return None

        dados['texto_original'] = texto_ingrediente
        return dados
        
    except google_exceptions.ResourceExhausted as e:
        raise QuotaExceededError(f"Cota da API do Gemini excedida: {e}")
    except Exception as e:
        print(f"   -> Erro ao processar resposta da IA para '{texto_ingrediente}': {e}")
        print(f"   -> Resposta recebida: {response.text if 'response' in locals() else 'N/A'}")
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

def buscar_receitas_nao_processadas(conn, limit=None):
    """Busca receitas que ainda não foram processadas pela IA."""
    query_str = "SELECT id, titulo, ingredientes_brutos FROM receitas WHERE processado_pela_llm = FALSE AND ingredientes_brutos IS NOT NULL ORDER BY id;"
    if limit:
        query_str = query_str.replace(";", f" LIMIT {limit};")
    query = text(query_str)
    return conn.execute(query).fetchall()

def salvar_dados_e_marcar_como_processada(conn, receita_id, titulo_corrigido, lista_ingredientes_estruturados):
    """Salva os dados processados."""
    update_query = text("""
        UPDATE receitas SET
            titulo = :titulo,
            ingredientes = :ingredientes_json,
            processado_pela_llm = TRUE,
            revisado = TRUE
        WHERE id = :receita_id;
    """)
    params = {
        "titulo": titulo_corrigido,
        "ingredientes_json": json.dumps(lista_ingredientes_estruturados, ensure_ascii=False),
        "receita_id": receita_id
    }
    conn.execute(update_query, params)

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
        print("Conectado ao PostgreSQL.")
    except Exception as e:
        print(f"ERRO ao conectar ao PostgreSQL: {e}")
        exit()

    api_calls_count = 0
    
    try:
        with engine.connect() as conn_leitura:
            receitas_para_processar = buscar_receitas_nao_processadas(conn_leitura, limit=args.limit)
        
        total_receitas = len(receitas_para_processar)
        if not receitas_para_processar:
            print("Nenhuma receita nova para processar.")
        else:
            print(f"Encontradas {total_receitas} receitas para processar com IA.")

        print("\nIniciando processamento das receitas...")
        
        for i, row in enumerate(receitas_para_processar):
            receita_id, titulo_bruto, ingredientes_brutos = row
            
            with engine.begin() as conn_escrita:
                try:
                    try:
                        titulo_corrigido_encoding = titulo_bruto.encode('latin1').decode('utf-8')
                    except:
                        titulo_corrigido_encoding = titulo_bruto
                    
                    titulo_final = corrigir_titulo_receita_com_gemini(titulo_corrigido_encoding)
                    api_calls_count += 1
                    time.sleep(1.1)

                    if not ingredientes_brutos:
                        salvar_dados_e_marcar_como_processada(conn_escrita, receita_id, titulo_final, [])
                        continue
                    
                    lista_ingredientes_estruturados = []
                    sucesso_total_receita = True
                    
                    for texto_ingrediente in ingredientes_brutos:
                        if not texto_ingrediente.strip():
                            continue

                        dados_estruturados = parse_ingrediente_com_regras(texto_ingrediente)
                        
                        if not dados_estruturados:
                            dados_estruturados = analisar_ingrediente_com_gemini(texto_ingrediente)
                            api_calls_count += 1
                            time.sleep(1.1)

                        if dados_estruturados == "IGNORE":
                            continue # Simplesmente pula para o próximo ingrediente
                        
                        if dados_estruturados:
                            lista_ingredientes_estruturados.append(dados_estruturados)
                        else:
                            print(f"\nFalha crítica ao processar ingrediente '{texto_ingrediente}' para a receita ID {receita_id}.")
                            sucesso_total_receita = False
                            break
                    
                    if sucesso_total_receita:
                        salvar_dados_e_marcar_como_processada(conn_escrita, receita_id, titulo_final, lista_ingredientes_estruturados)
                        print(f"   -> Receita ID {receita_id} ('{titulo_final}') foi processada e salva.")
                
                except Exception as e_receita:
                    print(f"\nErro ao processar a receita ID {receita_id}. Alterações desfeitas. Erro: {e_receita}")

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