# nutriai/migrar_ingredientes_brutos.py
import sqlite3
import os
import json
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv
from tqdm import tqdm

# --- Configuração ---
# O script está em 'nutriai/', o DB está na pasta 'data/' na raiz do projeto.
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
SQLITE_DB_PATH = os.path.join(project_root, 'data', 'nutriai.db')

dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')

def migrar_brutos():
    pg_engine = None
    sqlite_conn = None
    try:
        # --- Conexão com PostgreSQL ---
        db_url = URL.create(
            drivername="postgresql+psycopg2",
            username=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            host=os.getenv("POSTGRES_HOST"),
            port=os.getenv("POSTGRES_PORT"),
            database=os.getenv("POSTGRES_DB"),
            query={"client_encoding": "utf8"}
        )
        pg_engine = create_engine(db_url)
        print("✔️ Conectado ao PostgreSQL.")

        # --- Conexão com SQLite ---
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        print(f"✔️ Conectado ao SQLite em: {SQLITE_DB_PATH}")

        # 1. Ler todos os ingredientes brutos do SQLite e agrupar por receita
        print("[*] Lendo ingredientes brutos do banco de dados SQLite...")
        sqlite_cursor.execute("SELECT receita_id, descricao FROM ingredientes ORDER BY receita_id;")
        
        ingredientes_por_receita = {}
        for row in sqlite_cursor.fetchall():
            receita_id = row['receita_id']
            descricao = row['descricao'] if 'descricao' in row.keys() else None
            
            if receita_id not in ingredientes_por_receita:
                ingredientes_por_receita[receita_id] = []
            
            if descricao:
                ingredientes_por_receita[receita_id].append(descricao)
        
        print(f"🔍 Encontrados ingredientes brutos para {len(ingredientes_por_receita)} receitas no SQLite.")

        # 2. Atualizar o PostgreSQL
        print("[*] Atualizando a coluna 'ingredientes_brutos' no PostgreSQL...")
        with pg_engine.begin() as conn:
            update_query = text("UPDATE receitas SET ingredientes_brutos = :brutos WHERE id = :id")
            
            # <<< LINHA CORRIGIDA AQUI >>>
            for receita_id, lista_brutos in tqdm(ingredientes_por_receita.items(), desc="Migrando ingredientes brutos"):
                if lista_brutos:
                    conn.execute(update_query, {
                        "id": receita_id,
                        "brutos": json.dumps(lista_brutos)
                    })
        
        print("\n🎉 Migração dos ingredientes brutos concluída com sucesso!")

    except Exception as e:
        print(f"❌ Ocorreu um erro durante a migração dos dados brutos: {e}")
    finally:
        if sqlite_conn:
            sqlite_conn.close()
        if pg_engine:
            pg_engine.dispose()
        print("🔌 Conexões fechadas.")

if __name__ == "__main__":
    migrar_brutos()