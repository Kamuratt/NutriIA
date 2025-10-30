# api/pdf_generator.py (VERSÃO EXCELENTE FINALÍSSIMA v3)
from fastapi import HTTPException
import tempfile
import re
import math
from collections import defaultdict
from . import schemas
from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader
from markdown_it import MarkdownIt

# --- Funções de Normalização e Conversão de Unidades ---
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
        "dentes": "dente", "unidades": "unidade", "unidade(s)": "unidade", "gramas": "g",
        "kgs": "kg", "quilos": "kg", "fatias": "fatia", "pitadas": "pitada", "gotas": "gota",
        "folhas": "folha", "pedacos": "pedaco", "pedaços": "pedaco", "saquinhos": "saquinho",
        "cubos": "cubo", "ml": "ml", "mles": "ml", "mililitros": "ml", "litro": "litro",
        "l": "l", "litros": "litro", "latas": "lata", "vidros": "vidro", "pacotes": "pacote",
        "macos": "maço", "maços": "maço", "ramos": "ramo", "cachos": "cacho", "postas": "posta",
        "raminhos": "raminho", "cabeças": "cabeça", "cabecas": "cabeça", "ramalhete": "ramalhete",
        "embalagem": "embalagem"
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
    if quantidade == 1: return palavra
    s = palavra.lower().strip()
    mapa_singular_plural = {
        "xicara": "xicaras", "colher": "colheres", "dente": "dentes", "unidade": "unidades", "g": "g",
        "kg": "kg", "fatia": "fatias", "pitada": "pitadas", "gota": "gotas", "folha": "folhas",
        "pedaco": "pedacos", "saquinho": "saquinhos", "cubo": "cubos", "ml": "ml", "litro": "litros",
        "l": "l", "vez": "vezes", "copo": "copos", "grao": "graos", "raminho": "raminhos",
        "cabeca": "cabecas", "maço": "maços", "cacho": "cachos", "ramo": "ramos", "lata": "latas",
        "vidro": "vidros", "pacote": "pacotes", "posta": "postas", "ramalhete": "ramalhetes",
        "embalagem": "embalagens"
    }
    if s in mapa_singular_plural: return mapa_singular_plural[s]
    if s[-1] in 'rslz' and s not in ["arroz", "gas", "mais", "menos", "pires", "simples", "onibus", "lapis"]: return s + 'es'
    elif s[-1] == 'm': return s[:-1] + 'ns'
    elif s[-1] == 'l' and s[-2] in 'aeiou': return s[:-1] + 'is'
    elif s[-1] == 'o' and s == 'grao': return 'graos'
    elif s[-1] in 'aeiou': return s + 's'
    return s

# --- Constantes para Lista de Compras ---

NORMALIZACAO_NOMES = {
    "abobora italia": "abobora", "abóbora itália": "abobora", "abóbora de pescoço": "abobora", "abóbora moranga": "abobora", "jerimum": "abobora",
    "acafrao-da-terra em po": "acafrao em po", "cúrcuma": "acafrao", "curcuma": "acafrao",
    "alho em po": "alho em po",
    "azeite extra virgem": "azeite", "azeite de oliva": "azeite", "azeite extravirgem": "azeite",
    "oleo vegetal": "oleo", "óleo vegetal": "oleo", "oleo de girassol": "oleo", "óleo de soja": "oleo", "oleo de canola": "oleo", "oleo de milho": "oleo",
    "proteina texturizada de soja": "proteina de soja texturizada", "proteína texturizada de soja": "proteina de soja texturizada",
    "pts": "proteina de soja texturizada", "pt": "proteina de soja texturizada", "proteína de soja": "proteina de soja texturizada", "soja": "proteina de soja texturizada", # Simplifica 'soja' para PTS
    "pimentao vermelho": "pimentao", "pimentão vermelho": "pimentao",
    "pimentao verde": "pimentao", "pimentão verde": "pimentao",
    "pimentao amarelo": "pimentao", "pimentão amarelo": "pimentao",
    "arroz branco nao parborizado": "arroz branco", "arroz momiji": "arroz japones", "arroz": "arroz", "arroz integral": "arroz integral",
    "caldo de legum": "caldo de legumes",
    "tomat": "tomate", "tomates": "tomate", "tomate cereja": "tomate", "tomate italiano": "tomate",
    "molho shoyo": "shoyu",
    "brocoli": "brocolis", "brócolis": "brocolis", "bracolis": "brocolis", # CORRIGIDO TYPO
    "couveflor": "couve-flor", "couve flor": "couve-flor",
    "grao de bico": "grao-de-bico", "grão de bico": "grao-de-bico", "graodebico": "grao-de-bico",
    "batata doce": "batata-doce", "batata-doce roxa": "batata-doce", "batatadoce": "batata-doce",
    "pimenta do reino": "pimenta-do-reino", "pimentadoreino": "pimenta-do-reino",
    "ervas finas": "ervas", "cheiro verde": "cheiro-verde", "salsinha": "salsa", "cheiro-verde": "cheiro-verde", "tempero verde": "cheiro-verde",
    "amendoim torrado": "amendoim",
    "trigo para quibe": "trigo para quibe", "trigo de kibe": "trigo para quibe",
    "mandioca": "mandioca", "batata baroa": "mandioquinha", "batata-salsa": "mandioquinha",
    "leite de coco": "leite de coco", "leite de soja": "leite de soja", "leite vegetal": "leite vegetal",
    "cogumelo": "cogumelo", "champignon": "cogumelo", "shiitake": "cogumelo",
}

# Unidades que representam um item comprável inteiro/agrupado
UNIDADES_DESCRITIVAS_CONTAGEM = ["lata", "vidro", "pacote", "maço", "cacho", "ramo", "unidade", "cabeca", "tablete", "rolo", "sache", "embalagem", "ramalhete", "caixa", "envelope", "frasco"]
# Unidades base contáveis (não são de compra, mas são contáveis)
UNIDADES_BASE_CONTAVEIS = ["dente", "folha", "fatia", "pitada", "gota", "cubo", "raminho", "posta", "tira", "rodela"]

CONVERSOES = {
    "xicara_ml": 240.0, "colher_sopa_ml": 15.0, "colher_cha_ml": 5.0, "colher_sobremesa_ml": 10.0, "copo_americano_ml": 200.0, "copo_ml": 200.0,
    "alho_dentes_por_cabeca": 10.0, "saquinho_arroz_g": 90.0, "xicara_arroz_g": 185.0, "xicara_arroz integral_g": 195.0,
    "xicara_feijao_g": 180.0, "xicara_lentilha_g": 190.0, "xicara_grao-de-bico_g": 160.0, "xicara_aveia_g": 80.0,
    "xicara_farinha de trigo_g": 120.0, "colher_sopa_farinha de trigo_g": 7.5, "xicara_proteina de soja texturizada_g": 60.0,
    "xicara_acucar_g": 200.0, "colher_sopa_acucar_g": 12.0, "xicara_acucar mascavo_g": 180.0,
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

# --- Função Principal da Lista de Compras (Lógica Aprimorada com Priorização v3) ---

def gerar_lista_de_compras_aprimorada(receitas_db: list) -> list:
    """Agrega ingredientes, prioriza unidades de compra e formata a lista."""
    if not receitas_db: return []

    ingredientes_consolidados = defaultdict(lambda: {
        'g': 0.0, 'ml': 0.0,
        'unidade_base_contavel': defaultdict(float),
        'unidade_descritiva_contavel': defaultdict(float),
        'descricoes_texto': set() # Usar set para evitar duplicatas de texto ("a gosto", "a gosto")
    })

    basicos_ignorar_completamente = ["agua"]
    # Itens que só são ignorados se a quantidade for "a gosto"
    basicos_ignorar_se_a_gosto = ["sal", "tempero", "margarina", "gordura vegetal", "pimenta", "pimenta-do-reino", "oleo", "azeite"]

    for receita in receitas_db:
        # Garante que receita.ingredientes é sempre uma lista de dicts
        lista_ingredientes_receita = []
        raw_ingredientes = receita.ingredientes
        if isinstance(raw_ingredientes, list):
            lista_ingredientes_receita = [ing for ing in raw_ingredientes if isinstance(ing, dict)]
        elif isinstance(raw_ingredientes, dict): # Tenta lidar se for um dict inesperado
             lista_ingredientes_receita = [ing for ing in raw_ingredientes.values() if isinstance(ing, dict)]

        for ingrediente in lista_ingredientes_receita:
            nome_original = ingrediente.get("nome_ingrediente")
            quantidade_original = ingrediente.get("quantidade")
            unidade_original = (ingrediente.get("unidade") or "").strip()

            if not nome_original: continue
            nome_lower = nome_original.strip().lower()

            if any(basico in nome_lower for basico in basicos_ignorar_completamente): continue

            is_basico_a_gosto = False
            quantidade_str = str(quantidade_original).strip().lower()
            # Verifica nome exato ou com espaço no início/fim
            if any(basico == nome_lower or nome_lower.startswith(basico + ' ') or nome_lower.endswith(' ' + basico) for basico in basicos_ignorar_se_a_gosto):
                 if quantidade_original is None or not quantidade_str or "gosto" in quantidade_str or quantidade_str == "none" or quantidade_str == "q.b.":
                    is_basico_a_gosto = True
            if is_basico_a_gosto: continue

            # Normalização de Nome mais agressiva
            nome_norm = NORMALIZACAO_NOMES.get(nome_lower, nome_lower)
            nome_norm = re.sub(r'\(.*?\)|,".*?"|\'.*?\'| picado| ralado| cozido| grande| pequeno| médio| fresco| seca| desidratado| fatiado| em cubos| em tiras| sem semente| com semente', '', nome_norm, flags=re.IGNORECASE).strip()
            nome_norm_singular = plural_para_singular(nome_norm)
            if nome_norm_singular == "pimentadoreino": nome_norm_singular = "pimenta-do-reino"
            if not nome_norm_singular: continue # Pula se o nome ficou vazio após a limpeza

            unidade_norm_singular = plural_para_singular(unidade_original) if unidade_original else ""

            qtde_float = 0.0
            is_numeric = False
            try:
                # Tenta converter float, tratando vírgula como ponto decimal
                qtde_float = float(quantidade_str.replace(",", "."))
                is_numeric = True
            except (ValueError, TypeError):
                # Tenta converter frações "X/Y" ou "X Y/Z"
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
                elif unidade_norm_singular in ["ml", "litro", "l", "xicara", "colher", "copo americano", "copo"]:
                    fator_ml = 1.0
                    if unidade_norm_singular == "litro" or unidade_norm_singular == "l": fator_ml = 1000.0
                    elif unidade_norm_singular == "xicara": fator_ml = CONVERSOES.get("xicara_ml", 240.0)
                    elif unidade_norm_singular == "copo americano" or unidade_norm_singular == "copo": fator_ml = CONVERSOES.get("copo_americano_ml", 200.0)
                    elif unidade_norm_singular == "colher":
                        if "sopa" in unidade_original.lower(): fator_ml = CONVERSOES.get("colher_sopa_ml", 15.0)
                        elif "cha" in unidade_original.lower(): fator_ml = CONVERSOES.get("colher_cha_ml", 5.0)
                        elif "sobremesa" in unidade_original.lower(): fator_ml = CONVERSOES.get("colher_sobremesa_ml", 10.0)
                        else: fator_ml = CONVERSOES.get("colher_sopa_ml", 15.0) # Default para 'colher'
                    consolidado['ml'] += qtde_float * fator_ml
                elif unidade_norm_singular in ["g", "kg"]:
                    fator_g = 1.0 if unidade_norm_singular == "g" else 1000.0
                    consolidado['g'] += qtde_float * fator_g
                elif unidade_norm_singular == "saquinho" and "arroz" in nome_norm_singular:
                     consolidado['g'] += qtde_float * CONVERSOES.get("saquinho_arroz_g", 90.0)
                elif unidade_norm_singular in UNIDADES_BASE_CONTAVEIS:
                     consolidado['unidade_base_contavel'][unidade_norm_singular] += qtde_float
                elif not unidade_norm_singular or unidade_norm_singular == 'none':
                     # Se já existe uma unidade descritiva (maço, cacho), não adiciona 'unidade' numérica
                     if not consolidado['unidade_descritiva_contavel']:
                         consolidado['unidade_descritiva_contavel']['unidade'] += qtde_float
                else: # Numérico com unidade desconhecida -> descritivo
                     desc = f"{quantidade_original} {unidade_original}".strip(); consolidado['descricoes_texto'].add(desc)
            elif quantidade_str and not is_basico_a_gosto: # Não numérico -> descritivo
                desc = f"{quantidade_original} {unidade_original}".strip(); consolidado['descricoes_texto'].add(desc)

    # --- Formatação Final com Priorização ---
    lista_final_unica = []
    for nome_sing, dados in sorted(ingredientes_consolidados.items()):
        partes_item = []
        ignorar_g_ml = False # Flag para ignorar g/ml se unidade de compra for usada

        # 1. Prioridade: Unidades Descritivas Contáveis (maço, lata, etc.)
        unidades_desc_cont = dados['unidade_descritiva_contavel']
        if unidades_desc_cont:
            temp_parts = []
            for unidade, total in sorted(unidades_desc_cont.items()):
                total_final = math.ceil(total)
                if total_final > 0:
                    unidade_display = singular_para_plural(unidade, total_final)
                    temp_parts.append(f"{int(total_final)} {unidade_display}")
            if temp_parts:
                partes_item.extend(temp_parts)
                ignorar_g_ml = True # Se listamos maço/lata/etc, não liste g/ml

        # 2. Prioridade: Unidades Base Contáveis (dente, folha, etc.) - Só se não teve descritiva
        unidades_base_cont = dados['unidade_base_contavel']
        if not ignorar_g_ml and unidades_base_cont:
            partes_base = []
            if nome_sing == 'alho' and 'dente' in unidades_base_cont:
                 total_dentes = math.ceil(unidades_base_cont.pop('dente'))
                 if total_dentes > 0:
                     dentes_por_cabeca = CONVERSOES.get("alho_dentes_por_cabeca", 10.0)
                     if total_dentes > dentes_por_cabeca * 0.7: # Se for mais que 70% de uma cabeça, compra 1 cabeça
                         cabecas = math.ceil(total_dentes / dentes_por_cabeca)
                         unidade_display = singular_para_plural("cabeca", cabecas)
                         partes_base.append(f"{cabecas} {unidade_display}")
                         ignorar_g_ml = True # Se comprou cabeça, não precisa de g/ml
                     else:
                         unidade_display = singular_para_plural("dente", total_dentes)
                         partes_base.append(f"{int(total_dentes)} {unidade_display}")

            for unidade, total in sorted(unidades_base_cont.items()):
                 total_final = math.ceil(total)
                 if total_final > 0:
                     unidade_display = singular_para_plural(unidade, total_final)
                     partes_base.append(f"{int(total_final)} {unidade_display}")

            if partes_base:
                partes_item.extend(partes_base)
                # Não seta 'ignorar_g_ml' aqui para permitir g/ml de outros formatos (ex: alho em pó)

        # 3. Prioridade: Peso (g -> kg) - Só se não teve contáveis
        total_g = dados['g']
        if not ignorar_g_ml and total_g > 0:
            if total_g > 500:
                total_kg = math.ceil(total_g / 500) * 0.5
                partes_item.append(f"{total_kg:.1f} kg".replace(".0", ""))
            else:
                 partes_item.append(f"{int(math.ceil(total_g))} g")
            ignorar_g_ml = True # Peso definido, não precisa de volume

        # 4. Prioridade: Volume (ml -> L) - Só se não teve contáveis ou peso
        total_ml = dados['ml']
        if not ignorar_g_ml and total_ml > 0:
            if total_ml > 500:
                 total_l = math.ceil(total_ml / 500) * 0.5
                 partes_item.append(f"{total_l:.1f} L".replace(".0", ""))
            else:
                 partes_item.append(f"{int(math.ceil(total_ml))} ml")

        # 5. Descrições textuais (adiciona sempre, como observação se houver outras unidades)
        descricoes = dados['descricoes_texto']
        descricoes_validas = sorted(list(d for d in descricoes if d))
        if descricoes_validas:
             if partes_item:
                 partes_item.append(f"({', '.join(descricoes_validas)})")
             else:
                 partes_item.extend(descricoes_validas)

        # Monta a string final do item
        if partes_item:
            partes_unicas = []
            for parte in partes_item:
                if parte not in partes_unicas: partes_unicas.append(parte)
            item_str = f"- {nome_sing.capitalize()}: {', '.join(partes_unicas)}"
            lista_final_unica.append(item_str)

    return sorted(lista_final_unica, key=lambda x: x.lstrip('- ').lower())


# --- Função Principal de Geração de PDF com WeasyPrint ---

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
        detailed_error = f"Erro WeasyPrint: {e}"
        if hasattr(e, 'message'): detailed_error += f" | Mensagem: {e.message}"
        raise HTTPException(status_code=500, detail=detailed_error)