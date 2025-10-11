# scripts/revisar_receitas_processadas.py
# VERSÃO ATUALIZADA COM A LÓGICA DA COLUNA 'revisado'
import json
import os
import time
import argparse
import google.generativeai as genai
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# --- CONFIGURAÇÕES ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Chave de API GOOGLE_API_KEY não encontrada.")
    genai.configure(api_key=api_key)
    print("API do Google Gemini configurada com sucesso.")
except (ValueError, TypeError) as e:
    print(f"ERRO DE CONFIGURAÇÃO: {e}")
    exit()

# --- FUNÇÕES DE CORREÇÃO COM IA (sem alterações) ---
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

def analisar_ingrediente_com_gemini(texto_ingrediente: str):
    """Usa a IA para reanalisar e padronizar um ingrediente."""
    model = genai.GenerativeModel('models/gemini-flash-latest')
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
        if isinstance(dados, list):
            dados = dados[0] if dados else None
        if not isinstance(dados, dict):
            return None
        dados['texto_original'] = texto_ingrediente
        return dados
    except Exception as e:
        print(f"   -> Erro na re-análise do ingrediente '{texto_ingrediente}': {e}")
        return None

# --- FUNÇÕES DE BANCO DE DADOS (ATUALIZADAS) ---

def buscar_receitas_para_revisar(conn, limit=None):
    """Busca receitas que foram processadas mas ainda não revisadas."""
    # ALTERAÇÃO 1: A query agora busca por 'revisado = FALSE'
    query_str = "SELECT id, titulo, ingredientes FROM receitas WHERE processado_pela_llm = TRUE AND revisado = FALSE ORDER BY id;"
    if limit:
        query_str = query_str.replace(";", f" LIMIT {limit};")
        
    query = text(query_str)
    result = conn.execute(query).fetchall()
    return result

def atualizar_receita_revisada(conn, receita_id, titulo_novo, ingredientes_novos):
    """Atualiza a receita e marca como revisada."""
    # ALTERAÇÃO 2: A query agora define 'revisado = TRUE'
    update_query = text("""
        UPDATE receitas SET
            titulo = :titulo,
            ingredientes = :ingredientes,
            revisado = TRUE
        WHERE id = :id;
    """)
    params = {
        "id": receita_id,
        "titulo": titulo_novo,
        "ingredientes": json.dumps(ingredientes_novos, ensure_ascii=False)
    }
    conn.execute(update_query, params)

# --- FLUXO PRINCIPAL DE REVISÃO ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Revisa receitas já processadas no banco de dados.")
    parser.add_argument("--limit", type=int, help="Número máximo de receitas para revisar.")
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

    print("\nIniciando revisão de receitas já processadas...")
    with engine.connect() as conn:
        # ALTERAÇÃO 3: Chamando a função com o novo nome
        receitas_para_revisar = buscar_receitas_para_revisar(conn, limit=args.limit)

    total_receitas = len(receitas_para_revisar)
    
    if not total_receitas:
        print("✅ Nenhuma receita para revisar. Todas já estão atualizadas!")
    else:
        print(f"Encontradas {total_receitas} receitas para revisar.")

    for i, row in enumerate(receitas_para_revisar):
        receita_id, titulo_bruto, ingredientes_antigos = row
        print(f"\nRevisando Receita ID {receita_id} ({i+1}/{total_receitas})...")
        
        with engine.begin() as conn:
            try:
                try:
                    titulo_corrigido_encoding = titulo_bruto.encode('latin1').decode('utf-8')
                except:
                    titulo_corrigido_encoding = titulo_bruto
                
                titulo_final = corrigir_titulo_receita_com_gemini(titulo_corrigido_encoding)
                print(f"   -> Título: '{titulo_bruto}' -> '{titulo_final}'")
                time.sleep(1.1)

                ingredientes_novos = []
                ingredientes_antigos_lista = ingredientes_antigos if ingredientes_antigos else []

                for ingrediente_antigo in ingredientes_antigos_lista:
                    texto_original = ingrediente_antigo.get("texto_original")
                    if not texto_original: continue

                    ingrediente_corrigido = analisar_ingrediente_com_gemini(texto_original)
                    if ingrediente_corrigido:
                        ingredientes_novos.append(ingrediente_corrigido)
                    else:
                        print(f"   -> Falha ao re-analisar ingrediente: '{texto_original}'")
                        ingredientes_novos.append(ingrediente_antigo)
                    time.sleep(1.1)

                atualizar_receita_revisada(conn, receita_id, titulo_final, ingredientes_novos)
                # ALTERAÇÃO 4: Mensagem de sucesso atualizada
                print(f"   -> ✅ Receita ID {receita_id} foi revisada e marcada como 'revisado'.")

            except Exception as e:
                print(f"❌ Erro ao revisar a receita ID {receita_id}. Alterações desfeitas. Erro: {e}")

    print("\nProcesso de revisão concluído.")