import tempfile
import re
import math
from collections import defaultdict
from . import schemas
from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader
from markdown_it import MarkdownIt

def normalizar_texto(texto: str) -> str:
    """Tenta decodificar texto para UTF-8, com fallback para ASCII."""
    if not texto: return ""
    try: return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        try: return texto.encode('utf-8', 'ignore').decode('utf-8')
        except Exception: return str(texto).encode('ascii', 'ignore').decode('ascii')

def plural_para_singular(palavra: str) -> str:
    """Converte unidades comuns para o singular para agregação."""
    p = palavra.lower().strip()
    mapa_plural_singular = {
        "xicaras": "xicara", "xicaras (cha)": "xicara", "xícaras": "xicara",
        "colheres": "colher", "colheres (sopa)": "colher", "colheres (cha)": "colher", "colheres (sobremesa)": "colher",
        "dentes": "dente",
        "unidades": "unidade", "unidade(s)": "unidade",
        "gramas": "g", "kgs": "kg", "quilos": "kg",
        "fatias": "fatia",
        "pitadas": "pitada",
        "gotas": "gota",
        "folhas": "folha",
        "pedacos": "pedaco", "pedaços": "pedaco",
        "saquinhos": "saquinho",
        "cubos": "cubo",
        "ml": "ml", "mles": "ml", "mililitros": "ml",
        "litro": "litro", "l": "l", "litros": "litro",
        "latas": "lata",
        "vidros": "vidro",
        "pacotes": "pacote",
        "macos": "maço", "maços": "maço",
        "ramos": "ramo",
        "cachos": "cacho",
        "postas": "posta",
        "raminhos": "raminho",
        "cabeças": "cabeça", "cabecas": "cabeça",
    }
    if p in mapa_plural_singular: return mapa_plural_singular[p]
    if len(p) > 2 and p.endswith('s'):
        if p.endswith('oes'): return p[:-3] + 'ao'
        if p.endswith('aes'): return p[:-3] + 'ao'
        if p.endswith('eis') and len(p) > 3: return p[:-2] + 'l'
        if p.endswith('ns'): return p[:-1]
        if p.endswith('res'): return p[:-2] + 'r'
        if p[-2] in 'aeiou' and p not in ["gas", "mais", "menos", "pires", "simples", "onibus", "lapis", "arroz"]:
            return p[:-1]
    return p

def singular_para_plural(palavra: str, quantidade: float) -> str:
    """Converte unidade singular para plural se quantidade != 1."""
    if quantidade == 1:
        return palavra
    s = palavra.lower().strip()
    mapa_singular_plural = {
        "xicara": "xicaras", "colher": "colheres", "dente": "dentes", "unidade": "unidades",
        "g": "g", "kg": "kg", "fatia": "fatias", "pitada": "pitadas", "gota": "gotas",
        "folha": "folhas", "pedaco": "pedacos", "saquinho": "saquinhos", "cubo": "cubos",
        "ml": "ml", "litro": "litros", "l": "l", "vez": "vezes", "copo": "copos",
        "grao": "graos", "raminho": "raminhos", "cabeca": "cabecas", "maço": "maços",
        "cacho": "cachos", "ramo": "ramos", "lata": "latas", "vidro": "vidros",
        "pacote": "pacotes", "posta": "postas",
    }
    if s in mapa_singular_plural: return mapa_singular_plural[s]
    if s[-1] in 'rslz' and s not in ["arroz", "gas", "mais", "menos", "pires", "simples", "onibus", "lapis"]: return s + 'es'
    elif s[-1] == 'm': return s[:-1] + 'ns'
    elif s[-1] == 'l' and s[-2] in 'aeiou': return s[:-1] + 'is'
    elif s[-1] == 'o' and s == 'grao': return 'graos'
    elif s[-1] in 'aeiou': return s + 's'
    return s

NORMALIZACAO_NOMES = {
    "abobora italia": "abobora", "abóbora itália": "abobora",
    "acafrao-da-terra em po": "acafrao em po", "cúrcuma": "acafrao", "curcuma": "acafrao",
    "alho em po": "alho em po",
    "azeite extra virgem": "azeite", "azeite de oliva": "azeite", "azeite extravirgem": "azeite",
    "oleo vegetal": "oleo", "óleo vegetal": "oleo", "oleo de girassol": "oleo",
    "proteina texturizada de soja": "proteina de soja texturizada", "proteína texturizada de soja": "proteina de soja texturizada",
    "pts": "proteina de soja texturizada", "pt": "proteina de soja texturizada",
    "pimentao vermelho": "pimentao", "pimentão vermelho": "pimentao",
    "pimentao verde": "pimentao", "pimentão verde": "pimentao",
    "pimentao amarelo": "pimentao", "pimentão amarelo": "pimentao",
    "arroz branco nao parborizado": "arroz branco", "arroz momiji": "arroz japones",
    "caldo de legum": "caldo de legumes",
    "tomat": "tomate",
    "molho shoyo": "shoyu",
    "brocoli": "brocolis", "brócolis": "brocolis", "bracolis": "brocolis", # Normaliza brócolis
    "couveflor": "couve-flor", "couve flor": "couve-flor",
    "grao de bico": "grao-de-bico", "grão de bico": "grao-de-bico",
    "batata doce": "batata-doce",
    "pimenta do reino": "pimenta-do-reino", "pimentadoreino": "pimenta-do-reino",
    "ervas finas": "ervas",
}

# Unidades que representam um item comprável inteiro/agrupado
UNIDADES_DESCRITIVAS_CONTAGEM = [
    "lata", "vidro", "pacote", "maço", "cacho", "ramo", "unidade", "cabeca", "tablete", "rolo", "sache", "embalagem"
]

# Unidades base contáveis (não são de compra, mas são contáveis)
UNIDADES_BASE_CONTAVEIS = ["dente", "folha", "fatia", "pitada", "gota", "cubo", "raminho", "posta", "tira"]

CONVERSOES = {
    "xicara_ml": 240.0, "colher_sopa_ml": 15.0, "colher_cha_ml": 5.0, "colher_sobremesa_ml": 10.0, "copo_americano_ml": 200.0,
    "alho_dentes_por_cabeca": 10.0,
    "saquinho_arroz_g": 90.0,
    "xicara_arroz_g": 185.0, "xicara_arroz integral_g": 195.0, "xicara_feijao_g": 180.0,
    "xicara_lentilha_g": 190.0, "xicara_grao-de-bico_g": 160.0, "xicara_aveia_g": 80.0,
    "xicara_farinha de trigo_g": 120.0, "colher_sopa_farinha de trigo_g": 7.5,
    "xicara_proteina de soja texturizada_g": 60.0, "xicara_acucar_g": 200.0,
}

def get_g_per_ml(nome_ingrediente):
    """Estima densidade (g/ml) para conversão volume -> peso."""
    nome_lower = nome_ingrediente.lower()
    if "farinha" in nome_lower or "aveia" in nome_lower: return 0.6
    if "acucar" in nome_lower: return 0.8
    if "arroz" in nome_lower or "grao" in nome_lower or "lentilha" in nome_lower: return 0.8
    if "proteina de soja" in nome_lower: return 0.3
    if "oleo" in nome_lower or "azeite" in nome_lower: return 0.9
    return 1.0

def gerar_lista_de_compras_aprimorada(receitas_db: list) -> list:
    """Agrega ingredientes, prioriza unidades de compra e formata a lista."""
    if not receitas_db: return []

    ingredientes_consolidados = defaultdict(lambda: {
        'g': 0.0,
        'ml': 0.0,
        'unidade_base_contavel': defaultdict(float),
        'unidade_descritiva_contavel': defaultdict(float),
        'descricoes_texto': []
    })

    basicos_ignorar_completamente = ["agua"]
    basicos_ignorar_se_a_gosto = ["sal", "tempero", "margarina", "gordura vegetal", "pimenta", "pimenta-do-reino", "oleo", "azeite"] # Óleo/Azeite só se for a gosto

    for receita in receitas_db:
        lista_ingredientes_receita = receita.ingredientes if isinstance(receita.ingredientes, list) else []
        for ingrediente in lista_ingredientes_receita:
            if not isinstance(ingrediente, dict): continue

            nome_original = ingrediente.get("nome_ingrediente")
            quantidade_original = ingrediente.get("quantidade")
            unidade_original = (ingrediente.get("unidade") or "").strip()

            if not nome_original: continue
            nome_lower = nome_original.strip().lower()

            if any(basico in nome_lower for basico in basicos_ignorar_completamente): continue

            is_basico_a_gosto = False
            quantidade_str = str(quantidade_original).strip().lower()
            if any(basico == nome_lower or basico + ' ' in nome_lower for basico in basicos_ignorar_se_a_gosto):
                 if quantidade_original is None or not quantidade_str or "gosto" in quantidade_str or quantidade_str == "none" or quantidade_str == "q.b.":
                    is_basico_a_gosto = True
            if is_basico_a_gosto: continue

            nome_norm = NORMALIZACAO_NOMES.get(nome_lower, nome_lower)
            nome_norm = re.sub(r'\(.*?\)|,".*?"|\'.*?\'', '', nome_norm).strip()
            nome_norm_singular = plural_para_singular(nome_norm)
            if nome_norm_singular == "pimentadoreino": nome_norm_singular = "pimenta-do-reino"

            unidade_norm_singular = plural_para_singular(unidade_original) if unidade_original else ""

            qtde_float = 0.0
            is_numeric = False
            try:
                qtde_float = float(quantidade_str)
                is_numeric = True
            except (ValueError, TypeError):
                match_frac = re.match(r'(\d+)\s*/\s*(\d+)', quantidade_str)
                match_mixed = re.match(r'(\d+)\s+(\d+)\s*/\s*(\d+)', quantidade_str)
                if match_mixed:
                    i, n, d = map(int, match_mixed.groups()); qtde_float = i + n / d if d else 0; is_numeric = bool(d)
                elif match_frac:
                    n, d = map(int, match_frac.groups()); qtde_float = n / d if d else 0; is_numeric = bool(d)

            consolidado = ingredientes_consolidados[nome_norm_singular]
            if is_numeric and qtde_float > 0:
                if unidade_norm_singular in UNIDADES_DESCRITIVAS_CONTAGEM:
                    consolidado['unidade_descritiva_contavel'][unidade_norm_singular] += qtde_float
                elif unidade_norm_singular in ["ml", "litro", "l", "xicara", "colher", "copo americano"]:
                    fator_ml = 1.0
                    if unidade_norm_singular == "litro" or unidade_norm_singular == "l": fator_ml = 1000.0
                    elif unidade_norm_singular == "xicara": fator_ml = CONVERSOES.get("xicara_ml", 240.0)
                    elif unidade_norm_singular == "copo americano": fator_ml = CONVERSOES.get("copo_americano_ml", 200.0)
                    elif unidade_norm_singular == "colher":
                        if "sopa" in unidade_original.lower(): fator_ml = CONVERSOES.get("colher_sopa_ml", 15.0)
                        elif "cha" in unidade_original.lower(): fator_ml = CONVERSOES.get("colher_cha_ml", 5.0)
                        elif "sobremesa" in unidade_original.lower(): fator_ml = CONVERSOES.get("colher_sobremesa_ml", 10.0)
                        else: fator_ml = CONVERSOES.get("colher_sopa_ml", 15.0)
                    consolidado['ml'] += qtde_float * fator_ml
                elif unidade_norm_singular in ["g", "kg"]:
                    fator_g = 1.0 if unidade_norm_singular == "g" else 1000.0
                    consolidado['g'] += qtde_float * fator_g
                elif unidade_norm_singular == "saquinho" and "arroz" in nome_norm_singular:
                     consolidado['g'] += qtde_float * CONVERSOES.get("saquinho_arroz_g", 90.0)
                elif unidade_norm_singular in UNIDADES_BASE_CONTAVEIS:
                     consolidado['unidade_base_contavel'][unidade_norm_singular] += qtde_float
                elif not unidade_norm_singular or unidade_norm_singular == 'none':
                     consolidado['unidade_descritiva_contavel']['unidade'] += qtde_float
                else:
                     desc = f"{quantidade_original} {unidade_original}".strip(); consolidado['descricoes_texto'].append(desc)
            elif quantidade_str and not is_basico_a_gosto:
                desc = f"{quantidade_original} {unidade_original}".strip(); consolidado['descricoes_texto'].append(desc)

    lista_final_unica = []
    for nome_sing, dados in sorted(ingredientes_consolidados.items()):
        partes_item = []

        # 1. Prioridade Máxima: Unidades Descritivas Contáveis (maço, lata, etc.)
        unidades_desc_cont = dados['unidade_descritiva_contavel']
        if unidades_desc_cont:
            for unidade, total in sorted(unidades_desc_cont.items()):
                total_final = math.ceil(total)
                unidade_display = singular_para_plural(unidade, total_final)
                partes_item.append(f"{int(total_final)} {unidade_display}")
            dados['g'] = 0.0
            dados['ml'] = 0.0

        # 2. Prioridade Média: Unidades Base Contáveis (dente, folha, etc.)
        unidades_base_cont = dados['unidade_base_contavel']
        if not partes_item and unidades_base_cont:
            for unidade, total in sorted(unidades_base_cont.items()):
                 if unidade == 'dente' and nome_sing == 'alho':
                     continue
                 total_final = math.ceil(total)
                 unidade_display = singular_para_plural(unidade, total_final)
                 partes_item.append(f"{int(total_final)} {unidade_display}")

        if nome_sing == 'alho' and dados['unidade_base_contavel']['dente'] > 0:
             total_dentes = math.ceil(dados['unidade_base_contavel']['dente'])
             dentes_por_cabeca = CONVERSOES.get("alho_dentes_por_cabeca", 10.0)
             if total_dentes > dentes_por_cabeca * 0.6:
                 cabecas = math.ceil(total_dentes / dentes_por_cabeca)
                 unidade_display = singular_para_plural("cabeca", cabecas)
                 partes_item.append(f"{cabecas} {unidade_display}")
             else:
                 unidade_display = singular_para_plural("dente", total_dentes)
                 partes_item.append(f"{int(total_dentes)} {unidade_display}")
             dados['g'] = 0.0; dados['ml'] = 0.0

        # 3. Prioridade Baixa: Peso (g -> kg)
        total_g = dados['g']
        if not partes_item and total_g > 0:
            if total_g > 500:
                total_kg = math.ceil(total_g / 500) * 0.5
                partes_item.append(f"{total_kg:.1f} kg".replace(".0", ""))
            else:
                 partes_item.append(f"{int(math.ceil(total_g))} g")

        # 4. Prioridade Baixa: Volume (ml -> L)
        total_ml = dados['ml']
        if not partes_item and total_ml > 0:
            if total_ml > 500:
                 total_l = math.ceil(total_ml / 500) * 0.5
                 partes_item.append(f"{total_l:.1f} L".replace(".0", ""))
            else:
                 partes_item.append(f"{int(math.ceil(total_ml))} ml")

        # 5. Descrições textuais
        descricoes = dados['descricoes_texto']
        if not partes_item and descricoes:
             descricoes_validas = sorted(list(set(d for d in descricoes if d)))
             if descricoes_validas:
                 partes_item.extend(descricoes_validas)

        if partes_item:
            item_str = f"- {nome_sing.capitalize()}: {', '.join(partes_item)}"
            lista_final_unica.append(item_str)
        elif descricoes:
             descricoes_validas = sorted(list(set(d for d in descricoes if d)))
             if descricoes_validas:
                 item_str = f"- {nome_sing.capitalize()}: {', '.join(descricoes_validas)}"
                 lista_final_unica.append(item_str)


    return sorted(lista_final_unica, key=lambda x: x.lstrip('- ').lower())

def criar_pdf_plano_excelente(plano_texto_md: str, receitas_detalhadas: list, user_data: schemas.UserRequestSchema, meta_calorica: float, lista_compras: list):
    """Gera um PDF renderizando um template HTML+CSS com WeasyPrint."""
    try:
        env = Environment(loader=FileSystemLoader('nutriai/api/templates'))
        template = env.get_template('plano_dieta.html')
    except Exception as e:
        print(f"ERRO CRÍTICO: Não foi possível carregar o template HTML 'nutriai/api/templates/plano_dieta.html'. Erro: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao carregar template do PDF: {e}")

    md = MarkdownIt()
    plano_html = md.render(plano_texto_md or "")

    dados = {
        "plano_html": plano_html,
        "receitas": receitas_detalhadas,
        "user": user_data,
        "meta_calorica": meta_calorica,
        "lista_compras": lista_compras
    }

    try:
        html_renderizado = template.render(dados)
    except Exception as e:
        print(f"ERRO CRÍTICO: Falha ao renderizar o template Jinja2. Erro: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao renderizar template do PDF: {e}")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf_path = tmp.name
            HTML(string=html_renderizado).write_pdf(pdf_path)
            return pdf_path
    except Exception as e:
        print(f"ERRO CRÍTICO: Falha ao gerar o PDF com WeasyPrint. Verifique dependências (Pango/Cairo). Erro: {e}")