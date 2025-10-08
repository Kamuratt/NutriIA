# scripts/diagnostico_unidades.py
import pandas as pd
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv

# --- Configuração ---
# Carrega o .env da pasta raiz do projeto
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')

def raio_x_das_unidades_postgres():
    """
    Executa uma consulta para listar todas as unidades distintas
    presentes na coluna JSONB 'ingredientes' no PostgreSQL.
    """
    engine = None
    try:
        # Conexão com o PostgreSQL
        db_url = URL.create(
            drivername="postgresql+psycopg2",
            username=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            host=os.getenv("POSTGRES_HOST"),
            port=os.getenv("POSTGRES_PORT"),
            database=os.getenv("POSTGRES_DB"),
            query={"client_encoding": "utf8"}
        )
        engine = create_engine(db_url)

        # Consulta de Debug para extrair unidades do JSONB
        # 1. jsonb_array_elements(ingredientes) -> Expande o array de ingredientes em linhas separadas
        # 2. elem->>'unidade' -> Extrai o valor da chave 'unidade' como texto de cada elemento
        query = text("""
            SELECT DISTINCT
                elem->>'unidade' AS unidade
            FROM
                receitas,
                jsonb_array_elements(ingredientes) AS elem
            WHERE
                elem->>'unidade' IS NOT NULL
                AND TRIM(elem->>'unidade') <> '';
        """)
        
        print("Executando consulta de Raio-X no banco PostgreSQL...")
        
        with engine.connect() as conn:
            df = pd.read_sql_query(query, conn)
        
        if df.empty:
            print("\n----------------------------------------------------")
            print("Resultado do Raio-X: Nenhuma unidade foi encontrada.")
            print("Isso pode significar que as receitas migradas não têm ingredientes ou unidades.")
            print("----------------------------------------------------")
        else:
            print("\n--- RAIO-X: Todas as Unidades Únicas Encontradas no Banco ---")
            # Ordena a lista para facilitar a visualização
            df_sorted = df.sort_values(by='unidade').reset_index(drop=True)
            print(df_sorted.to_string())
            print("---------------------------------------------------------")

    except Exception as e:
        print(f"Ocorreu um erro: {e}")
    finally:
        if engine:
            engine.dispose()

if __name__ == "__main__":
    raio_x_das_unidades_postgres()