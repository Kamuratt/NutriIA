# auditoria_dados.py (VERSÃO REFINADA)
import sqlite3
import pandas as pd
import unicodedata
import random
import difflib
import re

# É importante que este script importe as mesmas listas e funções do script principal
# para garantir que a auditoria seja consistente com o cálculo.
from calcular_nutrientes import carregar_tabela_taco, MAPEAMENTO_TACO_NORMALIZADO, BLACKLISTA_IGNORAR

ARQUIVO_BANCO = "nutriai.db"

def encontrar_alimento_localmente(nome_ingrediente: str, df_taco, conn):
    """
    Tenta encontrar um ingrediente usando todas as fontes locais, incluindo busca por similaridade.
    """
    if not nome_ingrediente: return None
    nome_normalizado = ''.join(c for c in unicodedata.normalize('NFD', nome_ingrediente.lower()) if unicodedata.category(c) != 'Mn')
    
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM taco_complementar WHERE alimento = ?", (nome_ingrediente,))
    if cursor.fetchone():
        return True

    nome_mapeado = MAPEAMENTO_TACO_NORMALIZADO.get(nome_normalizado)
    if nome_mapeado:
        nome_final_busca = ''.join(c for c in unicodedata.normalize('NFD', nome_mapeado.lower()) if unicodedata.category(c) != 'Mn')
    else:
        nome_final_busca = nome_normalizado

    if nome_final_busca in df_taco.index:
        return True

    alimentos_taco = df_taco.index.tolist()
    matches = difflib.get_close_matches(nome_final_busca, alimentos_taco, n=1, cutoff=0.8)
    if matches:
        return True
        
    return None

def auditar_banco():
    conn = None
    try:
        conn = sqlite3.connect(ARQUIVO_BANCO)
        cursor = conn.cursor()
        print(f"--- INICIANDO AUDITORIA DO BANCO: '{ARQUIVO_BANCO}' ---")

        print("\n[ PARTE 1: STATUS GERAL DO PIPELINE ]")
        cursor.execute("SELECT COUNT(*) FROM receitas;")
        total_receitas = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM receitas WHERE processado_pela_llm = 1;")
        total_llm = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM receitas WHERE nutrientes_calculados = 1;")
        total_calculado = cursor.fetchone()[0]

        if total_receitas == 0:
            print("O banco de dados não contém nenhuma receita ainda.")
            return

        perc_llm = (total_llm / total_receitas) * 100 if total_receitas > 0 else 0
        perc_calculado = (total_calculado / total_receitas) * 100 if total_receitas > 0 else 0

        print(f"Total de Receitas no Banco: {total_receitas}")
        print(f"Receitas Processadas pela IA (LLM): {total_llm} ({perc_llm:.2f}%)")
        print(f"Receitas com Nutrientes Calculados: {total_calculado} ({perc_calculado:.2f}%)")
        
        print("\n[ PARTE 2: ANÁLISE DE QUALIDADE DOS CÁLCULOS ]")
        if total_calculado > 0:
            tabela_taco = carregar_tabela_taco()
            if tabela_taco is None: return

            cursor.execute("SELECT id, titulo FROM receitas WHERE nutrientes_calculados = 1")
            receitas_calculadas = cursor.fetchall()
            
            qualidade = {'excelente': [], 'bom': [], 'ruim': []}
            ingredientes_nao_encontrados = set()
            
            blacklist_pattern = r'\b(' + '|'.join(re.escape(term) for term in BLACKLISTA_IGNORAR) + r')\b'
            
            for receita_id, titulo in receitas_calculadas:
                cursor.execute("SELECT nome_ingrediente FROM ingredientes_estruturados WHERE receita_id = ?", (receita_id,))
                ingredientes = cursor.fetchall()
                
                ingredientes_relevantes = 0
                ingredientes_encontrados_count = 0
                
                for (nome,) in ingredientes:
                    if re.search(blacklist_pattern, nome.lower()):
                        continue
                    
                    ingredientes_relevantes += 1
                    if encontrar_alimento_localmente(nome, tabela_taco, conn) is not None:
                        ingredientes_encontrados_count += 1
                    else:
                        ingredientes_nao_encontrados.add(nome)

                if ingredientes_relevantes > 0:
                    taxa_acerto = (ingredientes_encontrados_count / ingredientes_relevantes) * 100
                else:
                    taxa_acerto = 100.0

                resultado = (titulo, f"{ingredientes_encontrados_count}/{ingredientes_relevantes} ({taxa_acerto:.1f}%)")
                if taxa_acerto >= 90:
                    qualidade['excelente'].append(resultado)
                elif 70 <= taxa_acerto < 90:
                    qualidade['bom'].append(resultado)
                else:
                    qualidade['ruim'].append(resultado)
            
            print(f"Qualidade Excelente (>= 90% dos ingredientes relevantes encontrados): {len(qualidade['excelente'])} receitas")
            print(f"Qualidade Boa (entre 70% e 90%): {len(qualidade['bom'])} receitas")
            print(f"Qualidade Ruim (< 70%): {len(qualidade['ruim'])} receitas")

            # --- MUDANÇA APLICADA AQUI ---
            # O cabeçalho da PARTE 3 só será impresso se houver algo para mostrar.
            if qualidade['ruim'] or ingredientes_nao_encontrados:
                print("\n[ PARTE 3: AMOSTRAGEM E PRÓXIMOS PASSOS ]")
                
                if qualidade['ruim']:
                    amostra = random.choice(qualidade['ruim'])
                    print(f"\nExemplo de Qualidade RUIM: '{amostra[0]}' - (Ingredientes encontrados: {amostra[1]})")

                if ingredientes_nao_encontrados:
                    print("\nPara melhorar a qualidade, adicione os seguintes ingredientes ao MAPEAMENTO_TACO em 'calcular_nutrientes.py':")
                    for item in sorted(list(ingredientes_nao_encontrados))[:15]:
                        print(f'   - "{item.lower()}": "???"')

    except Exception as e:
        print(f"\nOcorreu um erro durante a auditoria: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    auditar_banco()