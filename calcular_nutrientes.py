# calcular_nutrientes.py (VERSÃO CORRIGIDA E VALIDADA)
import pandas as pd
import sqlite3
import unicodedata
import difflib
import json
import os
import time
import re
import google.generativeai as genai
from dotenv import load_dotenv

ARQUIVO_BANCO = "nutriai.db"
load_dotenv()

BLACKLISTA_IGNORAR = {
    'água', 'agua', 'sal', 'gelo', 'palito de dente', 'papel chumbo',
    'receita de', 'a gosto', 'quanto baste', 'q.b.',
    'fritadeira elétrica', 'cravo-da-índia', 'ervas finas', 'pimenta biquinho'
}

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Chave de API não encontrada. Verifique seu arquivo .env")
    genai.configure(api_key=api_key)
    print("API do Google Gemini configurada.")
except (ValueError, TypeError) as e:
    print(f"ERRO: {e}")
    exit()

def carregar_tabela_taco(caminho_csv: str = "tabela_taco_processada.csv"):
    try:
        df = pd.read_csv(caminho_csv)
        df['alimento_normalizado'] = df['alimento'].astype(str).str.lower().apply(
            lambda x: ''.join(c for c in unicodedata.normalize('NFD', x) if unicodedata.category(c) != 'Mn')
        )
        df.set_index('alimento_normalizado', inplace=True)
        print("✔️ Tabela TACO carregada e normalizada com sucesso.")
        return df
    except Exception as e:
        print(f"❌ ERRO ao carregar a Tabela TACO: {e}")
        return None

def padronizar_unidade(unidade: str) -> str:
    if not unidade: return 'unidade'
    u_normalizada = ''.join(c for c in unicodedata.normalize('NFD', unidade.lower()) if unicodedata.category(c) != 'Mn')
    u_limpa = u_normalizada.replace('(', '').replace(')', '').strip()
    mapeamento = {
        'xicara': 'xicara', 'xicaras': 'xicara', 'xicara de cha': 'xicara', 'xicara cha': 'xicara',
        'colher de sopa': 'colher de sopa', 'colheres de sopa': 'colher de sopa', 'colher sopa': 'colher de sopa', 'sopa': 'colher de sopa', 'colher': 'colher de sopa', 'colheres': 'colher de sopa',
        'colher de cha': 'colher de cha', 'colheres de cha': 'colher de cha', 'colher cha': 'colher de cha', 'colher de sobremesa': 'colher de sobremesa', 'colher de cafe': 'colher de cafe', 'colher cafe': 'colher de cafe', 'colherzinha': 'colher de cha', 'colhercha': 'colher de cha',
        'dente': 'dente', 'dentes': 'dente', 'copo': 'copo', 'copos': 'copo', 'lata': 'lata', 'pacote': 'pacote',
        'grama': 'g', 'gramas': 'g', 'quilo': 'kg', 'quilos': 'kg', 'litro': 'l', 'litros': 'l', 'pitada': 'pitada',
        'unidade': 'unidade', 'unidades': 'unidade', 'fatia': 'fatia', 'fatias': 'fatia', 'sache': 'sache',
        'tablete': 'tablete', 'banda': 'banda', 'pedaco': 'pedaço', 'pote': 'pote', 'cabeça': 'cabeça', 'cabecas': 'cabeça', 'maco': 'maço',
        'cubo': 'cubo', 'cubos': 'cubo', 'folhas': 'unidade', 'folha': 'unidade', 'graos': 'unidade', 'polpa': 'unidade',
        'pires': 'pires', 'receita': 'receita', 'limao': 'unidade', 'medida': 'medida', 'gotas': 'gotas', 'bombons': 'unidade', 'bolas': 'bola'
    }
    return mapeamento.get(u_limpa, u_limpa)

CONVERSOES_PARA_GRAMAS = {
    ('genérico', 'xicara'): 240.0, ('genérico', 'copo'): 200.0, ('genérico', 'colher de sopa'): 15.0, ('genérico', 'colher de sobremesa'): 10.0, ('genérico', 'colher de cha'): 5.0, ('genérico', 'colher de cafe'): 2.5,
    ('açúcar', 'xicara'): 160.0, ('farinha de trigo', 'xicara'): 120.0, ('manteiga', 'colher de sopa'): 15.0, ('queijo ralado', 'colher de sopa'): 6.0,
    ('genérico', 'unidade'): 100.0, ('ovo', 'unidade'): 50.0, ('gema', 'unidade'): 20.0, ('cebola', 'unidade'): 120.0, ('limão', 'unidade'): 80.0,
    ('tomate', 'unidade'): 90.0, ('banana', 'unidade'): 100.0, ('abacaxi', 'unidade'): 1500.0, ('abobrinha', 'unidade'): 200.0, ('alho', 'dente'): 5.0,
    ('genérico', 'dente'): 5.0, ('genérico', 'pitada'): 1.0, ('genérico', 'fatia'): 20.0, ('queijo coalho', 'fatia'): 30.0, ('presunto', 'fatia'): 15.0,
    ('genérico', 'lata'): 250.0, ('genérico', 'pacote'): 200.0, ('genérico', 'sache'): 10.0, ('genérico', 'tablete'): 25.0, ('abacate', 'banda'): 250.0,
    ('genérico', 'banda'): 500.0, ('genérico', 'pedaço'): 50.0, ('genérico', 'cabeça'): 200.0, ('alho', 'cabeça'): 40.0, ('genérico', 'maço'): 100.0,
    ('genérico', 'cubo'): 20.0, ('leite em pó', 'colher de sopa'): 9.0, ('requeijão', 'pote'): 200.0, ('farinha de mandioca', 'xicara'): 150.0,
    ('azeite de oliva', 'colher de cha'): 4.5, ('molho de pimenta', 'colher de sopa'): 15.0, ('genérico', 'polpa'): 100.0, ('genérico', 'folha'): 2.0,
    ('genérico', 'pires'): 80.0, ('genérico', 'receita'): 0.0, ('pimentão vermelho', 'pedaço'): 100.0, ('pimentão verde', 'unidade'): 150.0,
    ('pimentão', 'unidade'): 150.0, ('genérico', 'medida'): 150.0, ('genérico', 'gotas'): 0.05, ('sonho de valsa', 'unidade'): 20.0, ('sorvete', 'bola'): 60.0
}

CONVERSOES_PARA_GRAMAS_NORMALIZADO = {(''.join(c for c in unicodedata.normalize('NFD', k[0]) if unicodedata.category(c) != 'Mn'), k[1]): v for k, v in CONVERSOES_PARA_GRAMAS.items()}

# --- DICIONÁRIO CORRIGIDO ---
MAPEAMENTO_TACO = {
    # --- Mapeamentos que JÁ ESTAVAM CORRETOS ---
    "acucar mascavo": "Açúcar, mascavo", "acucar cristal": "Açúcar, cristal", "açúcar": "Açúcar, cristal",
    "leite": "Leite, de vaca, integral, pó", "leite em po": "Leite, de vaca, integral, pó",
    "oleo": "Óleo, de soja", "fermento": "Fermento em pó, químico", "bacon": "Toucinho, frito", "peito de frango": "Frango, peito, sem pele, cru",
    "leite de coco": "Leite, de coco", "carne moida": "Carne, bovina, acém, moído, cru", "amido de milho": "Milho, amido, cru", "maisena": "Milho, amido, cru",
    "azeite": "Azeite, de oliva, extra virgem", "molho de tomate": "Tomate, molho industrializado", "requeijao": "Queijo, requeijão, cremoso", "queijo mussarela": "Queijo, mozarela", "queijo": "Queijo, prato",
    "canela": "canela, pó", "abobora": "Abóbora, moranga, crua", "abobrinha": "Abobrinha, italiana, crua",
    "cheiro-verde": "Salsa, crua", "salsinha": "Salsa, crua", "proteina texturizada de soja": "Soja, extrato solúvel, pó", "proteina de soja": "Soja, extrato solúvel, pó",
    "pts": "Soja, extrato solúvel, pó", "linguica suina": "Lingüiça, porco, crua", "doce de leite": "Doce, de leite, cremoso",
    "leite condensado": "Leite, condensado", "iogurte natural": "Iogurte, natural", "aveia": "Aveia, flocos, crua",
    "ovo": "Ovo, de galinha, inteiro, cru", "ovos": "Ovo, de galinha, inteiro, cru", "alho": "Alho, cru", "cebola": "Cebola, crua", "batata": "Batata, inglesa, crua",
    "milho": "Milho, verde, enlatado, drenado", "ervilha": "Ervilha, enlatada, drenada", "palmito": "Palmito, pupunha, em conserva",
    "manteiga": "Manteiga, com sal", "margarina": "Margarina, com óleo interesterificado, com sal (65%de lipídeos)", "abacate": "Abacate, cru",
    "tomate": "Tomate, com semente, cru", "cenoura": "Cenoura, crua", "cebolinha": "Cebolinha, crua",
    "farinha": "Farinha, de trigo", "limao": "Limão, tahiti, cru", "mel": "Mel, de abelha",
    "raspas da casca de limao": "Limão, tahiti, cru",
    "molho de pimenta": "Pimentão, vermelho, cru",
    "acai": "Açaí, polpa, congelada",
    "pimenta-do-reino": "pimenta do reino, pó", "gengibre": "gengibre, cru", "brigadeiro branco": "Doce, de leite, cremoso",
    "leite vegetal": "Soja, extrato solúvel, natural, fluido", "oleo vegetal": "Óleo, de soja", "azeite de oliva": "Azeite, de oliva, extra virgem",
    "farelo de aveia": "Aveia, flocos, crua", "farinha de aveia": "Aveia, flocos, crua",
    "goiabada": "Goiaba, doce, cascão",
    "farinha de trigo refinada": "Farinha, de trigo",
    "pao de lo": "Bolo, pronto, simples",
    "sal grosso": "Tempero a base de sal",
    "salsichas": "Salsicha, viena, enlatada",
    "sonho de valsa": "Chocolate, ao leite",
    "sorvete": "sorvete, massa, baunilha",
    "licor": "Cana, aguardente 1",
    "massa para salgados assados": "Pastel, massa, crua",
}


MAPEAMENTO_TACO_NORMALIZADO = {''.join(c for c in unicodedata.normalize('NFD', k) if unicodedata.category(c) != 'Mn'): v for k, v in MAPEAMENTO_TACO.items()}

# --- FUNÇÃO CORRIGIDA ---
def buscar_nutrientes_com_gemini(nome_ingrediente: str, cursor):
    print(f"      -> TACO falhou. Consultando a IA sobre '{nome_ingrediente}'...")
    model = genai.GenerativeModel('models/gemini-flash-latest')
    
    prompt = f'''
    Forneça uma estimativa dos dados nutricionais para 100g de "{nome_ingrediente}", com base em alimentos comuns no Brasil.
    Os nutrientes que preciso são: "calorias" (kcal), "proteina" (g), "lipideos" (g), "carboidratos" (g), e "fibras" (g).
    Retorne APENAS o objeto JSON, sem nenhum texto adicional, markdown ou explicação. Exemplo:
    {{"calorias": 123.4, "proteina": 5.6, "lipideos": 7.8, "carboidratos": 9.0, "fibras": 1.2}}
    '''
    try:
        time.sleep(4.5)
        # CORREÇÃO: Passando a variável 'prompt' para a função
        response = model.generate_content(prompt)
        
        # Limpando a resposta da IA para garantir que seja um JSON válido
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if not match:
            raise ValueError("Resposta da IA não contém um JSON válido.")
        
        json_text = match.group(0)
        dados_nutricionais = json.loads(json_text)

        cursor.execute("""
            INSERT OR IGNORE INTO taco_complementar (alimento, calorias, proteina, lipideos, carboidratos, fibras)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            nome_ingrediente, dados_nutricionais.get('calorias'), dados_nutricionais.get('proteina'),
            dados_nutricionais.get('lipideos'), dados_nutricionais.get('carboidratos'), dados_nutricionais.get('fibras')
        ))
        print(f"      -> IA respondeu. Resultado preparado para salvar.")
        return pd.Series(dados_nutricionais)
    except Exception as e:
        print(f"          -> Erro na consulta de nutrientes à IA: {e}")
        return None


def encontrar_alimento_na_taco(nome_ingrediente: str, df_taco, cursor):
    if not nome_ingrediente: return None
    nome_normalizado = ''.join(c for c in unicodedata.normalize('NFD', nome_ingrediente.lower()) if unicodedata.category(c) != 'Mn')
    
    cursor.execute("SELECT calorias, proteina, lipideos, carboidratos, fibras FROM taco_complementar WHERE alimento = ?", (nome_ingrediente,))
    resultado_cache = cursor.fetchone()
    if resultado_cache:
        print(f"   -> Encontrado '{nome_ingrediente}' no banco de dados complementar (cache).")
        return pd.Series(dict(zip(['calorias', 'proteina', 'lipideos', 'carboidratos', 'fibras'], resultado_cache)))

    nome_mapeado = MAPEAMENTO_TACO_NORMALIZADO.get(nome_normalizado)
    if nome_mapeado:
        nome_final_busca = ''.join(c for c in unicodedata.normalize('NFD', nome_mapeado.lower()) if unicodedata.category(c) != 'Mn')
    else:
        nome_final_busca = nome_normalizado

    if nome_final_busca in df_taco.index:
        return df_taco.loc[nome_final_busca]
        
    alimentos_taco = df_taco.index.tolist()
    matches = difflib.get_close_matches(nome_final_busca, alimentos_taco, n=1, cutoff=0.8)
    if matches:
        return df_taco.loc[matches[0]]
        
    return buscar_nutrientes_com_gemini(nome_ingrediente, cursor)

def converter_para_gramas(ingrediente: dict):
    nome = ingrediente.get('nome_ingrediente')
    unidade = padronizar_unidade(ingrediente.get('unidade'))
    quantidade = ingrediente.get('quantidade')
    if quantidade is None: return 0.0
    try:
        quantidade = float(quantidade)
    except (ValueError, TypeError):
        return 0.0
        
    if unidade in ['g', 'gramas']: return quantidade
    if unidade in ['kg', 'quilos']: return quantidade * 1000
    if unidade in ['ml']: return quantidade
    if unidade in ['l', 'litros']: return quantidade * 1000
    
    if nome and unidade:
        nome_normalizado = ''.join(c for c in unicodedata.normalize('NFD', nome.lower()) if unicodedata.category(c) != 'Mn')
        peso = CONVERSOES_PARA_GRAMAS_NORMALIZADO.get((nome_normalizado, unidade))
        if peso is not None: return quantidade * peso
        
        peso = CONVERSOES_PARA_GRAMAS_NORMALIZADO.get(('generico', unidade))
        if peso is not None: return quantidade * peso
        
    print(f"   -> AVISO: Não foi encontrada conversão para '{ingrediente.get('quantidade')} {ingrediente.get('unidade')}' de {nome}.")
    return 0.0

def calcular_nutrientes_receita(receita_id: int, cursor, df_taco):
    cursor.execute("SELECT * FROM ingredientes_estruturados WHERE receita_id = ?", (receita_id,))
    ingredientes = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]
    if not ingredientes: return None, True
    
    totais = {'calorias': 0.0, 'proteina': 0.0, 'lipideos': 0.0, 'carboidratos': 0.0, 'fibras': 0.0}
    blacklist_pattern = r'\b(' + '|'.join(re.escape(term) for term in BLACKLISTA_IGNORAR) + r')\b'
    
    for ing in ingredientes:
        nome_ingrediente_lower = ing['nome_ingrediente'].lower()
        if re.search(blacklist_pattern, nome_ingrediente_lower):
            print(f"   -> Ignorando ingrediente não relevante: '{ing['nome_ingrediente']}'")
            continue

        peso_em_gramas = converter_para_gramas(ing)
        if peso_em_gramas > 0:
            dados_taco = encontrar_alimento_na_taco(ing['nome_ingrediente'], df_taco, cursor)
            if dados_taco is not None:
                fator = peso_em_gramas / 100.0
                for nutriente in totais.keys():
                    if nutriente in dados_taco and pd.notna(dados_taco[nutriente]):
                        try:
                            totais[nutriente] += float(dados_taco[nutriente]) * fator
                        except (ValueError, TypeError):
                            continue
            else:
                print(f"   -> AVISO FINAL: Ingrediente '{ing['nome_ingrediente']}' não encontrado. Receita será pulada.")
                return None, False
    return totais, True

def salvar_nutrientes_no_banco(receita_id: int, totais: dict, cursor):
    cursor.execute("""
        INSERT OR REPLACE INTO informacoes_nutricionais
            (receita_id, calorias_total, proteina_total, lipideos_total, carboidratos_total, fibras_total)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        receita_id, totais['calorias'], totais['proteina'], totais['lipideos'],
        totais['carboidratos'], totais['fibras']
    ))
    cursor.execute("UPDATE receitas SET nutrientes_calculados = 1 WHERE id = ?", (receita_id,))
    print(f"✔️ Nutrientes da receita {receita_id} preparados para salvar.")


if __name__ == "__main__":
    tabela_taco_df = carregar_tabela_taco()
    if tabela_taco_df is not None:
        conn = sqlite3.connect(ARQUIVO_BANCO)
        try:
            cursor = conn.cursor()
            print("\nAVISO: O script está configurado para reprocessar TODAS as receitas.")
            cursor.execute("UPDATE receitas SET nutrientes_calculados = 0")
            conn.commit()
            
            cursor.execute("SELECT id, titulo FROM receitas WHERE processado_pela_llm = 1 AND nutrientes_calculados = 0")
            receitas_para_calcular = cursor.fetchall()
            
            if not receitas_para_calcular:
                print("\nNenhuma nova receita para calcular.")
            else:
                print(f"\nEncontradas {len(receitas_para_calcular)} receitas para (re)calcular os nutrientes.")
            
            for receita_id, titulo in receitas_para_calcular:
                print(f"\n--- Calculando nutrientes para: '{titulo}' (ID: {receita_id}) ---")
                
                totais_nutricionais, sucesso = calcular_nutrientes_receita(receita_id, cursor, tabela_taco_df)
                
                if sucesso and totais_nutricionais is not None:
                    salvar_nutrientes_no_banco(receita_id, totais_nutricionais, cursor)
                    conn.commit()
                    print(f"--- SUCESSO: Receita '{titulo}' foi salva permanentemente no banco! ---")
                elif not sucesso:
                    print(f"--- FALHA: Alterações para a receita '{titulo}' foram descartadas (rollback). ---")
                    conn.rollback()
                else: # sucesso is True, mas totais is None (receita sem ingredientes)
                    conn.commit() 
                    print(f"--- SUCESSO: Receita '{titulo}' processada (sem ingredientes a calcular) e salva. ---")

        except Exception as e_geral:
            print(f"❌ Ocorreu um erro geral e o script PAROU: {e_geral}")
            import traceback
            traceback.print_exc()
        finally:
            if conn:
                conn.close()
                print("\nProcesso de cálculo de nutrientes concluído.")