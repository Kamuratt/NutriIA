import json
import os
import re
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv

# Configuração
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path if os.path.exists(dotenv_path) else os.path.join(os.path.dirname(__file__), '.env'))

def conectar_banco():
    try:
        db_url = URL.create("postgresql+psycopg2", username=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST"), port=os.getenv("POSTGRES_PORT"), database=os.getenv("POSTGRES_DB"))
        return create_engine(db_url)
    except Exception as e: print(f"Erro DB: {e}"); exit()

def corrigir_mojibake(texto: str) -> str:
    if not texto or not isinstance(texto, str): return texto
    try: return texto.encode('latin-1').decode('utf-8')
    except: pass
    
    substituicoes = {
        'Ã£': 'ã', 'Ã©': 'é', 'Ã': 'í', 'Ã³': 'ó', 'Ãª': 'ê', 'Ãº': 'ú', 'Ã§': 'ç', 
        'ÃRr': 'à', 'Ã¢': 'â', 'Ãµ': 'õ', 'Ã': 'Á', 'Ã‰': 'É', 'Ã“': 'Ó',
        'nÃ£o': 'não', 'entÃ£o': 'então', 'feijÃ£o': 'feijão', 'limÃ£o': 'limão',
        'Â': '', 'â€“': '-', 'Ã ': 'à'
    }
    for errado, certo in substituicoes.items(): texto = texto.replace(errado, certo)
    texto = re.sub(r'^\s*.*(corrigid|padronizad|abaixo|segue).*?\n', '', texto, flags=re.IGNORECASE)
    return texto.strip()

def limpar_ingredientes(ingredientes_json):
    if not ingredientes_json: return None
    dado = ingredientes_json
    if isinstance(dado, str):
        try: dado = json.loads(dado)
        except: return ingredientes_json
    
    if isinstance(dado, list):
        for ing in dado:
            if isinstance(ing, dict):
                ing['nome_ingrediente'] = corrigir_mojibake(ing.get('nome_ingrediente', ''))
                ing['unidade'] = corrigir_mojibake(ing.get('unidade', ''))
                ing['observacao'] = corrigir_mojibake(ing.get('observacao', ''))
                if 'texto_original' in ing: ing['texto_original'] = corrigir_mojibake(ing['texto_original'])
    return json.dumps(dado, ensure_ascii=False)

def executar_sanitizacao():
    engine = conectar_banco()
    print("Iniciando sanitização INTELIGENTE...")
    
    with engine.connect() as conn:
        receitas = conn.execute(text("SELECT id, titulo, modo_preparo, ingredientes FROM receitas")).fetchall()
    
    count = 0
    print(f"Verificando {len(receitas)} receitas...")

    with engine.begin() as conn:
        for r in receitas:
            id_r, tit, prep, ing = r
            
            novo_tit = corrigir_mojibake(tit)
            novo_prep = corrigir_mojibake(prep)
            novo_ing_str = limpar_ingredientes(ing)
            
            ing_atual_str = json.dumps(ing, ensure_ascii=False) if ing else 'null'
            if novo_ing_str == 'null': novo_ing_str = None

            # LÓGICA INTELIGENTE: Se mudou algo, salva E INVALIDA o cálculo anterior
            if novo_tit != tit or novo_prep != prep or (novo_ing_str and novo_ing_str != ing_atual_str):
                conn.execute(
                    text("""
                        UPDATE receitas 
                        SET titulo=:t, modo_preparo=:p, ingredientes=:i, 
                            nutrientes_calculados=FALSE, -- INVALIDA CÁLCULO ANTIGO
                            informacoes_nutricionais=NULL -- LIMPA DADOS VELHOS
                        WHERE id=:id
                    """),
                    {"t": novo_tit, "p": novo_prep, "i": novo_ing_str, "id": id_r}
                )
                count += 1
                if count % 500 == 0: print(f"   -> {count} receitas corrigidas e marcadas para recálculo...")

    print(f"CONCLUÍDO. {count} receitas foram higienizadas e agora aguardam recálculo seguro.")

if __name__ == "__main__":
    executar_sanitizacao()