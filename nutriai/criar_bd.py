import sqlite3

# Define o nome do arquivo do nosso banco de dados.
NOME_BANCO = "nutriai.db"

def criar_tabelas():
    """
    Cria o arquivo do banco de dados e as tabelas 'receitas' e 'ingredientes'
    se elas ainda não existirem.
    """
    conn = None  # Inicia a conexão como nula
    try:
        # sqlite3.connect() cria o arquivo .db se ele não existir
        conn = sqlite3.connect(NOME_BANCO)
        cursor = conn.cursor()
        print(f"Banco de dados '{NOME_BANCO}' conectado com sucesso.")

        # --- Comando SQL para criar a tabela de receitas ---
        # A restrição UNIQUE na coluna 'url' é crucial para não inserirmos receitas duplicadas.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS receitas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            modo_preparo TEXT NOT NULL
        );
        """)
        print("Tabela 'receitas' verificada/criada.")

        # --- Comando SQL para criar a tabela de ingredientes ---
        # A 'FOREIGN KEY' cria a ligação oficial entre as tabelas.
        # Garante que um ingrediente só pode pertencer a uma receita que realmente existe.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receita_id INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            FOREIGN KEY (receita_id) REFERENCES receitas (id)
        );
        """)
        print("Tabela 'ingredientes' verificada/criada.")

        # Salva (commit) as alterações no arquivo do banco de dados
        conn.commit()
        print("Estrutura do banco de dados salva.")

    except sqlite3.Error as e:
        print(f"Ocorreu um erro ao criar o banco de dados: {e}")
    finally:
        # Garante que a conexão seja sempre fechada no final.
        if conn:
            conn.close()
            print("Conexão com o banco de dados fechada.")

criar_tabelas()