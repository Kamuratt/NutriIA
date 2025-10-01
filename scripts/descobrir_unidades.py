import sqlite3
import pandas as pd

ARQUIVO_BANCO = "nutriai.db"

def raio_x_das_unidades():
    """
    Executa uma consulta simples para listar TODAS as unidades distintas
    presentes no banco de dados para podermos depurar o filtro.
    """
    conn = None
    try:
        conn = sqlite3.connect(ARQUIVO_BANCO)
        
        # Consulta de Debug: Pega todas as unidades únicas que não sejam nulas
        query = """
        SELECT DISTINCT unidade FROM ingredientes_estruturados WHERE unidade IS NOT NULL;
        """
        
        print(f"Executando consulta de Raio-X no banco '{ARQUIVO_BANCO}'...")
        
        # Usamos o Pandas para ler o resultado e exibi-lo
        df = pd.read_sql_query(query, conn)
        
        if df.empty:
            print("\n----------------------------------------------------")
            print("Resultado do Raio-X: Nenhuma unidade foi encontrada na tabela 'ingredientes_estruturados'.")
            print("Isso pode significar que o processo de enriquecimento ainda não salvou nenhuma receita com sucesso.")
            print("----------------------------------------------------")

        else:
            print("\n--- RAIO-X: Todas as Unidades Únicas Encontradas no Banco ---")
            print(df.to_string())
            print("---------------------------------------------------------")

    except Exception as e:
        print(f"Ocorreu um erro: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    raio_x_das_unidades()