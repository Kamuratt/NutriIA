import sqlite3
import json
import os
import time
import google.generativeai as genai
from dotenv import load_dotenv

# --- CONFIGURAÇÕES ---
ARQUIVO_BANCO = "nutriai.db"
load_dotenv()

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Chave de API não encontrada. Verifique seu arquivo .env")
    genai.configure(api_key=api_key)
    print("API do Google Gemini configurada com sucesso.")
except (ValueError, TypeError) as e:
    print(f"ERRO: {e}")
    exit()

def buscar_receitas_nao_processadas(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, titulo FROM receitas WHERE processado_pela_llm = 0;")
    return cursor.fetchall()

def buscar_ingredientes_da_receita(conn, receita_id):
    cursor = conn.cursor()
    cursor.execute("SELECT id, descricao FROM ingredientes WHERE receita_id = ?;", (receita_id,))
    return cursor.fetchall()

def analisar_ingrediente_com_gemini(texto_ingrediente: str):
    # Usando o modelo Flash, que é rápido e eficiente para esta tarefa.
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"""
    Analise o seguinte ingrediente de uma receita e extraia as informações em formato JSON.
    Se o texto contiver múltiplos ingredientes (ex: "sal e pimenta"), retorne uma LISTA de objetos JSON.
    Caso contrário, retorne um ÚNICO objeto JSON.
    Se uma informação não estiver presente, use o valor null. A quantidade deve ser um número.

    Exemplos:
    - Texto: "1/2 xícara de azeitonas pretas picadas" -> {{"nome": "azeitona preta", "quantidade": 0.5, "unidade": "xicara", "observacao": "picadas"}}
    - Texto: "Sal e pimenta a gosto" -> [{{"nome": "sal", "quantidade": null, "unidade": null, "observacao": "a gosto"}}, {{"nome": "pimenta", "quantidade": null, "unidade": null, "observacao": "a gosto"}}]

    Texto do Ingrediente para analisar: "{texto_ingrediente}"

    Retorne APENAS o objeto JSON ou a lista de objetos JSON.
    """
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"  -> Erro na API do Gemini: {e}")
        return None

def salvar_dados_estruturados(conn, receita_id, ingrediente_id, texto_original, dados_llm: dict):
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO ingredientes_estruturados 
        (receita_id, texto_original, nome_ingrediente, quantidade, unidade, observacao)
    VALUES (?, ?, ?, ?, ?, ?);
    """, (
        receita_id,
        texto_original,
        dados_llm.get("nome"),
        dados_llm.get("quantidade"),
        dados_llm.get("unidade"),
        dados_llm.get("observacao")
    ))

def marcar_receita_como_processada(conn, receita_id):
    cursor = conn.cursor()
    cursor.execute("UPDATE receitas SET processado_pela_llm = 1 WHERE id = ?;", (receita_id,))

# --- FLUXO PRINCIPAL ---
if __name__ == "__main__":
    conn = sqlite3.connect(ARQUIVO_BANCO)
    receitas_para_processar = buscar_receitas_nao_processadas(conn)
    
    if not receitas_para_processar:
        print("Nenhuma receita nova para processar.")
    else:
        print(f"Encontradas {len(receitas_para_processar)} novas receitas para processar com a IA.")

    # O 'try/finally' garante que a conexão com o banco seja fechada no final, mesmo se houver um erro.
    try:
        for receita_id, titulo_receita in receitas_para_processar:
            print(f"\n--- Processando Receita: '{titulo_receita}' (ID: {receita_id}) ---")
            ingredientes = buscar_ingredientes_da_receita(conn, receita_id)
            sucesso_total_receita = True
            
            for ingrediente_id, texto_ingrediente in ingredientes:
                print(f"  Analisando: '{texto_ingrediente}'")
                dados_resposta_ia = analisar_ingrediente_com_gemini(texto_ingrediente)
                
                if dados_resposta_ia:
                    if isinstance(dados_resposta_ia, list):
                        print(f"  -> IA retornou MÚLTIPLOS ingredientes: {dados_resposta_ia}")
                        for item in dados_resposta_ia:
                            salvar_dados_estruturados(conn, receita_id, ingrediente_id, texto_ingrediente, item)
                    elif isinstance(dados_resposta_ia, dict):
                        print(f"  -> IA retornou: {dados_resposta_ia}")
                        salvar_dados_estruturados(conn, receita_id, ingrediente_id, texto_ingrediente, dados_resposta_ia)
                else:
                    sucesso_total_receita = False
                    print(f"  -> Falha ao analisar o ingrediente. A receita será processada novamente mais tarde.")
                    # Se uma chamada de API falhar, pulamos para a próxima receita para não gastar mais tempo.
                    break 
                
                time.sleep(5) # Pausa para respeitar o limite de quota da API.

            # --- MUDANÇA PRINCIPAL AQUI ---
            # Se todos os ingredientes da receita foram processados com sucesso...
            if sucesso_total_receita:
                # ...marcamos a receita como processada...
                marcar_receita_como_processada(conn, receita_id)
                # ...e SALVAMOS (commit) o trabalho desta receita no banco.
                conn.commit()
                print(f"--- SUCESSO: Receita '{titulo_receita}' foi salva permanentemente no banco! ---")

    except Exception as e:
        print(f"Um erro geral ocorreu e o programa foi interrompido: {e}")
    finally:
        if conn:
            conn.close()
            print("\nProcesso de enriquecimento concluído.")