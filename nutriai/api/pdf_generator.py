from fastapi import HTTPException
import tempfile
from . import schemas
from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader
from markdown_it import MarkdownIt

def criar_pdf_plano_excelente(plano_texto_md: str, receitas_detalhadas: list, user_data: schemas.UserRequestSchema, meta_calorica: float):
    try:
        env = Environment(loader=FileSystemLoader('nutriai/api/templates'))
        template = env.get_template('plano_dieta.html')
    except Exception as e:
        print(f"ERRO TEMPLATE: {e}"); raise HTTPException(status_code=500, detail="Erro template")

    md = MarkdownIt()
    plano_html = md.render(plano_texto_md or "")

    receitas_view = []
    for r in receitas_detalhadas:
        # --- 1. Formata Ingredientes ---
        ings_view = []
        raw_ings = r.get("ingredientes", [])
        
        if isinstance(raw_ings, list):
            for ing in raw_ings:
                if isinstance(ing, dict):
                    nome = ing.get('nome_ingrediente', '')
                    qtd = ing.get('quantidade', '')
                    uni = ing.get('unidade', '')
                    obs = ing.get('observacao', '')
                    
                    if not nome: continue
                    
                    partes = []
                    if qtd and str(qtd).lower() != 'none': partes.append(str(qtd))
                    if uni and str(uni).lower() != 'none': partes.append(str(uni))
                    
                    s = f"{' '.join(partes)} de <b>{nome}</b>" if partes else f"<b>{nome}</b>"
                    if obs and str(obs).lower() != 'none': s += f" <small>({obs})</small>"
                    ings_view.append(s)

        # --- 2. Formata Modo de Preparo (CORREÇÃO DO TEXTO COLADO) ---
        preparo_bruto = r.get("modo_preparo", "")
        # Divide o texto em parágrafos sempre que tiver uma quebra de linha
        # Filtra linhas vazias para não criar buracos
        paragrafos_preparo = [p.strip() for p in preparo_bruto.split('\n') if p.strip()]

        receitas_view.append({
            "titulo": r.get("titulo"),
            "nutri_info": r.get("nutri_info"),
            "ingredientes": ings_view,
            "modo_preparo_paragrafos": paragrafos_preparo, # Passa lista, não string
            "dia_sugerido": r.get("dia_sugerido")
        })

    dados = {
        "plano_html": plano_html,
        "receitas": receitas_view,
        "user": user_data,
        "meta_calorica": meta_calorica
    }

    try:
        html_renderizado = template.render(dados)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            HTML(string=html_renderizado).write_pdf(tmp.name)
            return tmp.name
    except Exception as e:
        print(f"ERRO WEASYPRINT: {e}"); raise HTTPException(status_code=500, detail=f"Erro PDF: {e}")   