# migration.py (VERSÃO FINAL DE TESTE - SEM DOTENV)
import sqlite3
import json
import os
from sqlalchemy import create_engine, text

# --- Configuração de Caminhos ---
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
SQLITE_DB_PATH = os.path.join(project_root, 'data', 'nutriai.db')

# --- Credenciais fixadas para o teste final ---
db_host = "localhost"
db_name = "nutriai_db"
db_user = "admin"
db_port = "5432"
db_pass = "senhaforte123" # A senha que definimos no docker-compose.yml

# --- Início da Migração ---
sqlite_conn = None
pg_engine = None

def migrate():
    global sqlite_conn, pg_engine
    try:
        # ETAPA 1: Conectar ao SQLite
        print(f"[*] Conectando ao SQLite em: {SQLITE_DB_PATH}")
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        print("✅ Conectado ao SQLite.")

        # ETAPA 2: Conectar ao PostgreSQL com SQLAlchemy + pg8000
        print("[*] Conectando ao PostgreSQL com SQLAlchemy + pg8000...")
        db_url = f"postgresql+pg8000://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        pg_engine = create_engine(db_url)
        
        with pg_engine.connect() as pg_conn:
            print("✅ Conectado ao PostgreSQL.")

            # ETAPA 3: Criar a tabela
            create_table_query = text("""
            CREATE TABLE IF NOT EXISTS receitas (
                id INTEGER PRIMARY KEY, titulo TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
                modo_preparo TEXT NOT NULL, processado_pela_llm BOOLEAN DEFAULT FALSE,
                nutrientes_calculados BOOLEAN DEFAULT FALSE, ingredientes JSONB,
                informacoes_nutricionais JSONB
            );
            """)
            pg_conn.execute(create_table_query)
            pg_conn.commit()
            print("✅ Tabela 'receitas' garantida no PostgreSQL.")

            # ETAPA 4: Migrar os dados
            sqlite_cursor.execute("SELECT * FROM receitas")
            all_recipes = sqlite_cursor.fetchall()
            print(f"🔍 Encontradas {len(all_recipes)} receitas para migrar.")

            for recipe in all_recipes:
                receita_id = recipe['id']
                sqlite_cursor.execute("SELECT nome_ingrediente, quantidade, unidade, observacao, texto_original FROM ingredientes_estruturados WHERE receita_id = ?", (receita_id,))
                ingredientes_rows = sqlite_cursor.fetchall()
                ingredientes_list = [dict(row) for row in ingredientes_rows]
                sqlite_cursor.execute("SELECT calorias_total, proteina_total, lipideos_total, carboidratos_total, fibras_total FROM informacoes_nutricionais WHERE receita_id = ?", (receita_id,))
                nutri_row = sqlite_cursor.fetchone()
                nutri_dict = dict(nutri_row) if nutri_row else {}

                insert_query = text("""
                INSERT INTO receitas (id, titulo, url, modo_preparo, processado_pela_llm, nutrientes_calculados, ingredientes, informacoes_nutricionais)
                VALUES (:id, :titulo, :url, :modo_preparo, :proc_llm, :nutri_calc, :ingredientes, :info_nutri)
                ON CONFLICT (id) DO UPDATE SET
                    titulo = EXCLUDED.titulo, url = EXCLUDED.url, modo_preparo = EXCLUDED.modo_preparo,
                    processado_pela_llm = EXCLUDED.processado_pela_llm, nutrientes_calculados = EXCLUDED.nutrientes_calculados,
                    ingredientes = EXCLUDED.ingredientes, informacoes_nutricionais = EXCLUDED.informacoes_nutricionais;
                """)
                params = {
                    "id": receita_id, "titulo": recipe['titulo'], "url": recipe['url'],
                    "modo_preparo": recipe['modo_preparo'], "proc_llm": bool(recipe['processado_pela_llm']),
                    "nutri_calc": bool(recipe['nutrientes_calculados']),
                    "ingredientes": json.dumps(ingredientes_list),
                    "info_nutri": json.dumps(nutri_dict)
                }
                pg_conn.execute(insert_query, params)
            
            pg_conn.commit()
            print(f"\n🎉 Migração de {len(all_recipes)} receitas concluída com sucesso!")

    except Exception as e:
        print(f"❌ Ocorreu um erro durante a migração: {e}")
    finally:
        if sqlite_conn: sqlite_conn.close()
        if pg_engine: pg_engine.dispose()
        print("🔌 Conexões fechadas.")

if __name__ == "__main__":
    migrate()