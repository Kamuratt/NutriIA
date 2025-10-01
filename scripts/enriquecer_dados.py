import sqlite3
import json
import os
import time
import re
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from dotenv import load_dotenv
from tqdm import tqdm

# --- CONFIGURAÇÕES ---
ARQUIVO_BANCO = "../data/nutriai.db"
MAX_API_CALLS_PER_RUN = 250

load_dotenv()

class QuotaExceededError(Exception):
    """Exceção para quando a cota da API é atingida."""
    pass

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Chave de API não encontrada.")
    genai.configure(api_key=api_key)
    print("API do Google Gemini configurada com sucesso.")
except (ValueError, TypeError) as e:
    print(f"ERRO: {e}")
    exit()

# --- FUNÇÕES ---

def parse_ingrediente_com_regras(texto: str):
    if not texto: return None
    unidades = ['xícara', 'xícaras', 'colher', 'colheres', 'copo', 'copos', 'g', 'kg', 'ml', 'l', 'lata', 'latas', 'dente', 'dentes', 'pitada', 'pitadas', 'unidade', 'unidades', 'fatia', 'fatias', 'ramo', 'ramos', 'folha', 'folhas', 'tablete', 'tabletes', 'pacote', 'pacotes', 'sachê', 'sachês']
    padrao = r"^\s*(?P<quantidade>[\d\./,\s]+|\w+)\s+(?P<unidade>" + "|".join(unidades) + r"(?:s)?(?: de chá| de sopa)?)\s*(?:de\s+)?(?P<resto>.*)"
    match = re.search(padrao, texto.strip(), re.IGNORECASE)
    if match:
        dados = match.groupdict()
        nome, *obs_list = re.split(r'[,(]', dados.get("resto", "").strip(), 1)
        observacao = obs_list[0].strip('() ') if obs_list else None
        return {"nome": nome.strip(), "quantidade": dados.get("quantidade").strip(), "unidade": dados.get("unidade").strip(), "observacao": observacao}
    if "a gosto" in texto.lower() or "quanto baste" in texto.lower():
        return {"nome": texto.replace("a gosto", "").replace("quanto baste", "").strip(), "quantidade": None, "unidade": None, "observacao": "a gosto"}
    return None

def buscar_receitas_nao_processadas(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, titulo FROM receitas WHERE processado_pela_llm = 0;")
    return cursor.fetchall()

def buscar_ingredientes_da_receita(conn, receita_id):
    cursor = conn.cursor()
    cursor.execute("SELECT id, descricao FROM ingredientes WHERE receita_id = ?;", (receita_id,))
    return cursor.fetchall()

def salvar_dados_estruturados(conn, receita_id, ingrediente_id, texto_original, dados_proc: dict):
    cursor = conn.cursor()
    # Usamos INSERT OR IGNORE para evitar duplicatas se o script rodar de novo na mesma receita
    cursor.execute("""
    INSERT OR IGNORE INTO ingredientes_estruturados 
        (receita_id, texto_original, nome_ingrediente, quantidade, unidade, observacao)
    VALUES (?, ?, ?, ?, ?, ?);
    """, (
        receita_id, texto_original, dados_proc.get("nome"), dados_proc.get("quantidade"),
        dados_proc.get("unidade"), dados_proc.get("observacao")
    ))

def marcar_receita_como_processada(conn, receita_id):
    cursor = conn.cursor()
    cursor.execute("UPDATE receitas SET processado_pela_llm = 1 WHERE id = ?;", (receita_id,))

def analisar_ingrediente_com_gemini(texto_ingrediente: str):
    # --- CORREÇÃO DO ERRO DE DIGITAÇÃO AQUI ---
    model = genai.GenerativeModel('models/gemini-flash-latest') # Era GenerModel
    prompt = f"Analise o seguinte ingrediente: '{texto_ingrediente}' e retorne um JSON com 'nome', 'quantidade', 'unidade', 'observacao'."
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except google_exceptions.ResourceExhausted as e:
        raise QuotaExceededError(f"Cota da API do Gemini excedida: {e}")
    except Exception as e:
        print(f"  -> Erro na API do Gemini: {e}")
        return None

# --- FLUXO PRINCIPAL COM LÓGICA DE 2 PASSADAS ---
if __name__ == "__main__":
    conn = sqlite3.connect(ARQUIVO_BANCO, timeout=10)
    
    # --- PASSO 1: VARREDURA SOMENTE COM REGEX ---
    print("\n--- PASSO 1: Executando varredura rápida com Regex ---")
    receitas_para_processar = buscar_receitas_nao_processadas(conn)
    receitas_resolvidas_com_regex = 0
    if not receitas_para_processar:
        print("Nenhuma receita nova para processar.")
    else:
        for receita_id, titulo_receita in tqdm(receitas_para_processar, desc="Passo 1: Regex"):
            ingredientes = buscar_ingredientes_da_receita(conn, receita_id)
            if not ingredientes: # Pula receitas sem ingredientes
                marcar_receita_como_processada(conn, receita_id)
                continue

            todos_resolvidos_com_regex = True
            for ingrediente_id, texto_ingrediente in ingredientes:
                dados_estruturados = parse_ingrediente_com_regras(texto_ingrediente)
                if dados_estruturados:
                    salvar_dados_estruturados(conn, receita_id, ingrediente_id, texto_ingrediente, dados_estruturados)
                else:
                    todos_resolvidos_com_regex = False # Marca que esta receita precisará da IA
            
            if todos_resolvidos_com_regex:
                marcar_receita_como_processada(conn, receita_id)
                receitas_resolvidas_com_regex += 1
        
        conn.commit()
        print(f"\n{receitas_resolvidas_com_regex} receitas foram completamente resolvidas apenas com Regex.")

    # --- PASSO 2: PROCESSAMENTO HÍBRIDO PARA AS RECEITAS RESTANTES ---
    print("\n--- PASSO 2: Utilizando IA para as receitas complexas restantes ---")
    receitas_para_ia = buscar_receitas_nao_processadas(conn)
    api_calls_count = 0
    
    if not receitas_para_ia:
        print("Nenhuma receita restante para processar com a IA.")
    else:
        print(f"Encontradas {len(receitas_para_ia)} receitas que precisam da IA.")
        print(f"Limite de chamadas da API para esta execução: {MAX_API_CALLS_PER_RUN}")
        try:
            for receita_id, titulo_receita in tqdm(receitas_para_ia, desc="Passo 2: IA"):
                if api_calls_count >= MAX_API_CALLS_PER_RUN:
                    print(f"\nLimite de {MAX_API_CALLS_PER_RUN} chamadas da API atingido.")
                    break

                ingredientes = buscar_ingredientes_da_receita(conn, receita_id)
                sucesso_total_receita = True
                
                for ingrediente_id, texto_ingrediente in ingredientes:
                    # Tenta com Regex primeiro (para preencher o que já foi feito)
                    dados_estruturados = parse_ingrediente_com_regras(texto_ingrediente)
                    
                    if not dados_estruturados: # Se falhar, usa a IA
                        if api_calls_count >= MAX_API_CALLS_PER_RUN:
                            sucesso_total_receita = False; break

                        dados_estruturados = analisar_ingrediente_com_gemini(texto_ingrediente)
                        api_calls_count += 1
                        time.sleep(1.1)

                    if dados_estruturados:
                        if isinstance(dados_estruturados, list):
                            for item in dados_estruturados:
                                salvar_dados_estruturados(conn, receita_id, ingrediente_id, texto_ingrediente, item)
                        else:
                            salvar_dados_estruturados(conn, receita_id, ingrediente_id, texto_ingrediente, dados_estruturados)
                    else:
                        sucesso_total_receita = False; break
                
                if sucesso_total_receita:
                    marcar_receita_como_processada(conn, receita_id)
                    conn.commit()

        except QuotaExceededError as e:
            print(f"\n!!! ATENÇÃO: {e} !!!")
            print("O script foi interrompido e continuará no próximo ciclo.")
        except Exception as e:
            print(f"\nUm erro geral ocorreu no Passo 2: {e}")
        
        finally:
            if conn:
                conn.close()
            print("\nProcesso de enriquecimento concluído.")