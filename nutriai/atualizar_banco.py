import sqlite3

ARQUIVO_BANCO = "nutriai.db"

def atualizar_schema():
    """
    Atualiza o banco de dados adicionando a coluna de status
    e criando a nova tabela para ingredientes estruturados.
    """
    conn = None
    try:
        conn = sqlite3.connect(ARQUIVO_BANCO)
        cursor = conn.cursor()
        print(f"Conectado ao banco de dados '{ARQUIVO_BANCO}' para atualização.")

        try:
            # O comando ALTER TABLE adiciona uma nova coluna à tabela existente.
            # O DEFAULT 0 garante que todas as receitas atuais sejam marcadas como "não processadas".
            cursor.execute("""
            ALTER TABLE receitas ADD COLUMN processado_pela_llm INTEGER DEFAULT 0;
            """)
            print("Coluna 'processado_pela_llm' adicionada à tabela 'receitas'.")
        except sqlite3.OperationalError as e:
            # Este erro acontece se a coluna já existir. É um comportamento esperado.
            if "duplicate column name" in str(e):
                print("Aviso: A coluna 'processado_pela_llm' já existe.")
            else:
                raise e

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredientes_estruturados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receita_id INTEGER NOT NULL,
            texto_original TEXT NOT NULL,
            nome_ingrediente TEXT,
            quantidade REAL,
            unidade TEXT,
            observacao TEXT,
            FOREIGN KEY (receita_id) REFERENCES receitas (id)
        );
        """)
        print("Tabela 'ingredientes_estruturados' verificada/criada.")

        conn.commit()
        print("\nAtualização do banco de dados concluída com sucesso!")

    except sqlite3.Error as e:
        print(f"Ocorreu um erro ao atualizar o banco de dados: {e}")
    finally:
        if conn:
            conn.close()
            print("Conexão com o banco de dados fechada.")

atualizar_schema()