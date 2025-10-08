# C:\GitHub\NutriIA\nutriai\migration.py
import sqlite3
import json
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv

# --- Configuração de Caminhos ---
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
SQLITE_DB_PATH = os.path.join(project_root, 'data', 'nutriai.db')
dotenv_path = os.path.join(project_root, '.env')

# --- Início da Migração ---
sqlite_conn = None
pg_engine = None

def migrate():
    global sqlite_conn, pg_engine
    try:
        print("[*] Carregando variáveis de ambiente...")
        # <<< AQUI ESTÁ A CORREÇÃO DEFINITIVA >>>
        load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')
        
        print("✅ Variáveis carregadas. Verificando valores:")
        print(f"--> USER: '{os.getenv('POSTGRES_USER')}'")
        print(f"--> PASSWORD: '{os.getenv('POSTGRES_PASSWORD')[:10]}...'")
        print(f"--> HOST: '{os.getenv('POSTGRES_HOST')}'")
        print(f"--> PORT: '{os.getenv('POSTGRES_PORT')}'")
        print(f"--> DB: '{os.getenv('POSTGRES_DB')}'")

        # ETAPA 1: Conectar ao SQLite e decodificar da fonte (cp1252 -> Unicode)
        print(f"[*] Conectando ao SQLite em: {SQLITE_DB_PATH}")
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        sqlite_conn.text_factory = lambda b: b.decode('cp1252', errors='replace')
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        print("✅ Conectado ao SQLite.")

        # ETAPA 2: Conectar ao PostgreSQL garantindo o encoding do cliente
        print("[*] Conectando ao PostgreSQL com SQLAlchemy + psycopg2...")
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

        with pg_engine.begin() as pg_conn:
            print("✅ Conectado ao PostgreSQL e transação iniciada.")

            create_table_query = text("""
            CREATE TABLE IF NOT EXISTS receitas (
                id INTEGER PRIMARY KEY, 
                titulo TEXT NOT NULL, 
                url TEXT NOT NULL UNIQUE,
                modo_preparo TEXT NOT NULL, 
                processado_pela_llm BOOLEAN DEFAULT FALSE,
                nutrientes_calculados BOOLEAN DEFAULT FALSE, 
                ingredientes JSONB,
                informacoes_nutricionais JSONB
            );
            """)
            pg_conn.execute(create_table_query)
            print("✅ Tabela 'receitas' garantida no PostgreSQL.")

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
                    titulo = EXCLUDED.titulo, 
                    url = EXCLUDED.url, 
                    modo_preparo = EXCLUDED.modo_preparo,
                    processado_pela_llm = EXCLUDED.processado_pela_llm, 
                    nutrientes_calculados = EXCLUDED.nutrientes_calculados,
                    ingredientes = EXCLUDED.ingredientes, 
                    informacoes_nutricionais = EXCLUDED.informacoes_nutricionais;
                """)
                
                params = {
                    "id": receita_id,
                    "titulo": recipe['titulo'],
                    "url": recipe['url'],
                    "modo_preparo": recipe['modo_preparo'],
                    "proc_llm": bool(recipe['processado_pela_llm']),
                    "nutri_calc": bool(recipe['nutrientes_calculados']),
                    "ingredientes": json.dumps(ingredientes_list, ensure_ascii=False),
                    "info_nutri": json.dumps(nutri_dict, ensure_ascii=False)
                }
                pg_conn.execute(insert_query, params)
            
            print(f"\n🎉 Migração de {len(all_recipes)} receitas concluída com sucesso!")

    except Exception as e:
        print(f"❌ Ocorreu um erro durante a migração: {e}")
    finally:
        if sqlite_conn: 
            sqlite_conn.close()
        if pg_engine: 
            pg_engine.dispose()
        print("🔌 Conexões fechadas.")

if __name__ == "__main__":
    migrate()