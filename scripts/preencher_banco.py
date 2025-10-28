import sqlite3
import json
import os
import time

PASTA_A_PROCESSAR = "../data/receitas"
PASTA_PROCESSADOS = "../data/receitas_processadas"
ARQUIVO_BANCO = "../data/nutriai.db"

def criar_tabelas():
    conn = None
    try:
        conn = sqlite3.connect(ARQUIVO_BANCO)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS receitas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            modo_preparo TEXT NOT NULL
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receita_id INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            FOREIGN KEY (receita_id) REFERENCES receitas (id)
        );
        """)
        conn.commit()
    except sqlite3.Error as e:
        print(f"Ocorreu um erro na criação das tabelas: {e}")
    finally:
        if conn:
            conn.close()

def inserir_receita(conn, dados_receita: dict):
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO receitas (titulo, url, modo_preparo) VALUES (?, ?, ?)",
            (dados_receita['titulo'], dados_receita['url'], "\n".join(dados_receita['modo_preparo']))
        )
        receita_id = cursor.lastrowid
        ingredientes_para_inserir = [
            (receita_id, ing) for ing in dados_receita['ingredientes']
        ]
        cursor.executemany(
            "INSERT INTO ingredientes (receita_id, descricao) VALUES (?, ?)",
            ingredientes_para_inserir
        )
        return True
    except sqlite3.IntegrityError:
        # A receita já existe, consideramos um sucesso para fins de mover o arquivo.
        print(f"Aviso: Receita '{dados_receita['titulo']}' já existe. Será movida para processados.")
        return True
    except Exception as e:
        print(f"Erro inesperado ao inserir '{dados_receita['titulo']}': {e}")
        return False

def processar_e_mover_arquivos():
    """Implementa a estratégia de duas etapas: primeiro insere tudo, depois move tudo."""
    
    os.makedirs(PASTA_A_PROCESSAR, exist_ok=True)
    os.makedirs(PASTA_PROCESSADOS, exist_ok=True)

    arquivos_json = [f for f in os.listdir(PASTA_A_PROCESSAR) if f.endswith('.json')]
    if not arquivos_json:
        print(f"Nenhum arquivo .json encontrado em '{PASTA_A_PROCESSAR}'.")
        return

    print("--- ETAPA 1: Inserindo dados no Banco de Dados ---")
    arquivos_processados_com_sucesso = []
    conn = sqlite3.connect(ARQUIVO_BANCO)
    try:
        for nome_arquivo in arquivos_json:
            caminho_arquivo = os.path.join(PASTA_A_PROCESSAR, nome_arquivo)
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                try:
                    dados = json.load(f)
                    if inserir_receita(conn, dados):
                        # Se teve sucesso (ou era duplicata), adiciona à lista para mover depois
                        arquivos_processados_com_sucesso.append(nome_arquivo)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"Erro ao ler o arquivo '{nome_arquivo}': {e}. O arquivo não será movido.")
        conn.commit()
    except sqlite3.Error as e:
        print(f"Ocorreu um erro de banco de dados na Etapa 1: {e}")
        conn.rollback()
    finally:
        if conn:
            conn.close()
    
    print("\n--- ETAPA 2: Movendo arquivos processados ---")
    if not arquivos_processados_com_sucesso:
        print("Nenhum arquivo para mover.")
        return
        
    movidos = 0
    erros_movendo = 0
    for nome_arquivo in arquivos_processados_com_sucesso:
        caminho_origem = os.path.join(PASTA_A_PROCESSAR, nome_arquivo)
        caminho_destino = os.path.join(PASTA_PROCESSADOS, nome_arquivo)
        try:
            os.rename(caminho_origem, caminho_destino)
            print(f"Arquivo '{nome_arquivo}' movido com sucesso.")
            movidos += 1
        except Exception as e:
            print(f"Falha ao mover o arquivo '{nome_arquivo}': {e}")
            erros_movendo += 1
            
    print("\n--- RESUMO DA OPERAÇÃO ---")
    print(f"Arquivos inseridos/verificados no banco: {len(arquivos_processados_com_sucesso)}")
    print(f"Arquivos movidos para a pasta de processados: {movidos}")
    print(f"Erros ao mover arquivos: {erros_movendo}")
    print("----------------------------")

criar_tabelas()
processar_e_mover_arquivos()
print("\nProcesso concluído.")