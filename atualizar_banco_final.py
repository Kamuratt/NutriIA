# atualizar_banco_final.py
import sqlite3
ARQUIVO_BANCO = "nutriai.db"
conn = sqlite3.connect(ARQUIVO_BANCO)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS taco_complementar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alimento TEXT NOT NULL UNIQUE,
    calorias REAL, proteina REAL, lipideos REAL, carboidratos REAL, fibras REAL
);
""")
conn.commit()
conn.close()
print("Banco de dados atualizado com a tabela 'taco_complementar'.")