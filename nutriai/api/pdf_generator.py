# api/pdf_generator.py (VERSÃO FINAL 6.0 - Excelência Real)
from fpdf import FPDF
from . import schemas
from collections import defaultdict
import tempfile
import re
import math

# --- FUNÇÕES DE LIMPEZA (VERSÃO ROBUSTA FINAL++) ---
def normalizar_texto(texto: str) -> str:
    # (Sem mudanças)
    if not texto: return ""
    try: return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        try: return texto.encode('utf-8', 'ignore').decode('utf-8')
        except Exception: return str(texto).encode('ascii', 'ignore').decode('ascii') # Fallback para ASCII puro

def clean_for_pdf(text_to_clean: str) -> str:
    """
    Limpa o texto de forma AGRESSIVA (ASCII), remove acentos, caracteres especiais,
    LaTeX, lixo de tabela Markdown, espaços extras e expande PTS.
    """
    if not text_to_clean: return ""
    text = normalizar_texto(str(text_to_clean))

    # Expande PTS ANTES de outras limpezas
    text = re.sub(r'\bpts\b', 'Proteina Texturizada de Soja', text, flags=re.IGNORECASE)

    # Remove sintaxe LaTeX
    text = re.sub(r'\\frac{\s*}{\s*}', '', text)
    text = re.sub(r'\\times', 'x', text)
    # Remove linhas de tabela Markdown (mais robusto)
    text = re.sub(r'^\s*\|[:\-\s|]+\|?\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\|.*?\|\s*$', '', text, flags=re.MULTILINE) # Remove linhas de dados | a | b |
    # Remove múltiplos espaços em branco seguidos
    text = re.sub(r'\s{2,}', ' ', text)
    # Remove espaços no início/fim de cada linha
    text = "\n".join(line.strip() for line in text.split('\n'))

    replacements = {
        # Acentos (já incluídos)
        'á': 'a', 'à': 'a', 'â': 'a', 'ã': 'a', 'ä': 'a', 'é': 'e', 'è': 'e', 'ê': 'e', 'í': 'i', 'ì': 'i', 'î': 'i',
        'ó': 'o', 'ò': 'o', 'ô': 'o', 'õ': 'o', 'ú': 'u', 'ù': 'u', 'ü': 'u', 'ç': 'c', 'Á': 'A', 'À': 'A', 'Â': 'A',
        'Ã': 'A', 'É': 'E', 'È': 'E', 'Ê': 'E', 'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ó': 'O', 'Ò': 'O', 'Ô': 'O', 'Õ': 'O',
        'Ú': 'U', 'Ù': 'U', 'Ü': 'U', 'Ç': 'C',
        # Markdown e outros
        '°': ' graus', '**': '', '## ': '', '### ': '', '*': '-', '–': '-',
        '—': '-', '“': '"', '”': '"', '‘': "'", '’': "'", '#': '',
        # Frações comuns
        '½': '1/2', '¼': '1/4', '¾': '3/4', '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        # LaTeX e caracteres especiais
        '$': '', '\\': '', '{': '', '}': '',
        # Caractere de tabela Markdown remanescente
        '|': '',
    }

    for old, new in replacements.items(): text = text.replace(old, new)

    # Pequenas melhorias de pontuação
    text = re.sub(r'\s+([,.!?;:])', r'\1', text) # Remove espaço ANTES da pontuação
    text = re.sub(r'([,.!?;:])([a-zA-Z0-9])', r'\1 \2', text) # Garante espaço DEPOIS (se seguido por letra/num)

    # Força codificação ASCII e remove linhas que ficaram vazias
    linhas_limpas = [linha for linha in text.split('\n') if linha.strip()]
    texto_final = "\n".join(linhas_limpas)

    # Remove qualquer espaço extra no final
    return texto_final.strip().encode('ascii', 'ignore').decode('ascii')


# --- FUNÇÕES PLURAL/SINGULAR (REFINADAS) ---
def plural_para_singular(palavra: str) -> str:
    """Converte unidades comuns para o singular para agregação."""
    p = palavra.lower().strip()
    mapa_plural_singular = {
        "xicaras": "xicara", "xicaras (cha)": "xicara",
        "colheres": "colher", "colheres (sopa)": "colher", "colheres (cha)": "colher", "colheres (sobremesa)": "colher",
        "dentes": "dente",
        "unidades": "unidade",
        "gramas": "g", "kgs": "kg",
        "fatias": "fatia",
        "pitadas": "pitada",
        "gotas": "gota",
        "folhas": "folha",
        "pedacos": "pedaco",
        "saquinhos": "saquinho",
        "cubos": "cubo",
        "ml": "ml", "mles": "ml", # Corrige typo 'mles'
        "litro": "litro", "l": "l",
    }
    if p in mapa_plural_singular: return mapa_plural_singular[p]
    if len(p) > 2 and p.endswith('s'):
        if p.endswith('oes'): return p[:-3] + 'ao'
        if p.endswith('aes'): return p[:-3] + 'ao'
        if p.endswith('eis') and len(p) > 3: return p[:-2] + 'l'
        if p.endswith('ns'): return p[:-1]
        if p.endswith('res'): return p[:-2] + 'r'
        if p[-2] in 'aeiou':
             if p not in ["gas", "mais", "menos", "pires", "simples", "onibus", "lapis"]: return p[:-1]
    return p

def singular_para_plural(palavra: str, quantidade: float) -> str:
    """Converte unidade singular para plural SE quantidade > 1."""
    # Trata 0.5 e 1 como singular, mas 0 ou > 1 como plural
    if quantidade == 1 or (quantidade > 0 and quantidade < 1) :
        return palavra # Mantem singular

    s = palavra.lower().strip()
    mapa_singular_plural = {
        "xicara": "xicaras", "colher": "colheres", "dente": "dentes", "unidade": "unidades",
        "g": "g", "kg": "kg", "fatia": "fatias", "pitada": "pitadas", "gota": "gotas",
        "folha": "folhas", "pedaco": "pedacos", "saquinho": "saquinhos", "cubo": "cubos",
        "ml": "ml", "litro": "litros", "l": "l", "vez": "vezes", "copo": "copos",
        "grao": "graos", "raminho": "raminhos", "cabeca": "cabecas", # Adicionado cabeça
    }
    if s in mapa_singular_plural: return mapa_singular_plural[s]
    if s[-1] in 'rslz':
        if s not in ["arroz", "gas", "mais", "menos", "pires", "simples", "onibus", "lapis"]: return s + 'es'
    elif s[-1] == 'm': return s[:-1] + 'ns'
    elif s[-1] == 'l' and s[-2] in 'aeiou': return s[:-1] + 'is'
    elif s[-1] in 'aeiou': return s + 's'
    return s


# --- LISTA DE COMPRAS (LÓGICA DE UNIDADES DE COMPRA REFINADA) ---

NORMALIZACAO_NOMES = {
    "abobora italia": "abobora",
    "acafrao-da-terra em po": "acafrao em po", "curcuma": "acafrao", # Separa pó
    "alho em po": "alho em po",
    "azeite extra virgem": "azeite", "azeite de oliva": "azeite", "azeite extravirgem": "azeite",
    "oleo vegetal": "oleo", "oleo de girassol": "oleo",
    "proteina texturizada de soja": "proteina de soja texturizada",
    "pts": "proteina de soja texturizada", "pt": "proteina de soja texturizada", # Adiciona 'pt'
    "pimentao vermelho": "pimentao", "pimentao verde": "pimentao", "pimentao amarelo": "pimentao",
    "arroz branco nao parborizado": "arroz branco", "arroz momiji": "arroz japones",
    "caldo de legum": "caldo de legumes",
    "tomat": "tomate",
    "molho shoyo": "shoyu", # Simplifica
    # Adicionar mais conforme necessário
}

CONVERSOES = {
    "xicara_ml": 240.0, "colher_sopa_ml": 15.0, "colher_cha_ml": 5.0, "colher_sobremesa_ml": 10.0,
    "copo_americano_ml": 200.0,
    "alho_dentes_por_cabeca": 10.0,
    "saquinho_arroz_g": 90.0, # Estimativa
    # Estimativas de peso por volume (podem variar muito!)
    "xicara_arroz_g": 185.0, "xicara_arroz integral_g": 195.0,
    "xicara_feijao_g": 180.0, "xicara_lentilha_g": 190.0, "xicara_lentilhas_g": 190.0,
    "xicara_grao de bico_g": 160.0, "xicara_aveia_g": 80.0,
    "xicara_farinha de trigo_g": 120.0, "colher_sopa_farinha de trigo_g": 7.5,
    "xicara_farinha de aveia_g": 90.0, "colher_sopa_aveia_g": 10.0,
    "xicara_farinha de linhaca_g": 100.0, "colher_sopa_farinha de linhaca_g": 7.0,
    "xicara_farinha de arroz integral_g": 130.0,
    "xicara_proteina de soja texturizada_g": 60.0, # Leve
    "xicara_acucar_g": 200.0, "colher_sopa_acucar_g": 12.0, "xicara_acucar mascavo_g": 180.0,
    "colher_sopa_acucar mascavo_g": 10.0,
}

# Função para tentar obter conversão de peso
def get_g_per_ml(nome_ingrediente):
    # Muito simplificado - idealmente teria um DB de densidades
    if "farinha" in nome_ingrediente or "aveia" in nome_ingrediente: return 0.6
    if "acucar" in nome_ingrediente: return 0.8
    if "arroz" in nome_ingrediente or "grao" in nome_ingrediente or "lentilha" in nome_ingrediente: return 0.8
    if "proteina de soja" in nome_ingrediente: return 0.3
    return 1.0 # Default para líquidos ou desconhecidos

def gerar_lista_de_compras_aprimorada(receitas_db: list) -> list:
    if not receitas_db: return []
    ingredientes_agregados = defaultdict(lambda: defaultdict(float))
    ingredientes_descritivos = defaultdict(list)
    basicos_a_gosto_remover = ["sal", "agua", "tempero", "margarina", "gordura vegetal"] # Remover sempre se 'a gosto' ou None
    basicos_ignorar_qtde = ["agua"] # Ignorar mesmo com quantidade

    for receita in receitas_db:
        if receita.ingredientes:
            for ingrediente in receita.ingredientes:
                nome_original = ingrediente.get("nome_ingrediente")
                quantidade_original = ingrediente.get("quantidade")
                unidade_original = (ingrediente.get("unidade") or "").strip()

                if not nome_original: continue
                nome_lower = nome_original.strip().lower()

                # --- FILTRO DE BÁSICOS ---
                # Ignora completamente itens em basicos_ignorar_qtde
                if any(basico in nome_lower for basico in basicos_ignorar_qtde): continue
                # Remove itens em basicos_a_gosto_remover se for "a gosto" ou sem qtde
                is_basico_a_gosto = False
                if any(basico in nome_lower for basico in basicos_a_gosto_remover):
                    if not quantidade_original or (isinstance(quantidade_original, str) and ("gosto" in quantidade_original.lower() or quantidade_original.lower() == "none")):
                        is_basico_a_gosto = True
                if is_basico_a_gosto: continue
                # Remove itens onde a quantidade é explicitamente "None"
                if isinstance(quantidade_original, str) and quantidade_original.lower() == "none": continue
                # --- FIM FILTRO ---

                nome_norm = NORMALIZACAO_NOMES.get(nome_lower, nome_lower)
                nome_norm = re.sub(r'\(.*?\)', '', nome_norm).strip() # Remove (detalhes) do nome
                nome_norm_singular = plural_para_singular(nome_norm)

                unidade_norm_singular = plural_para_singular(unidade_original) if unidade_original else ""

                # --- AGREGAÇÃO NUMÉRICA (Tenta converter unidades para base comum se possível) ---
                try:
                    qtde_float = float(quantidade_original)
                    if qtde_float <= 0: continue # Ignora quantidade zero ou negativa

                    # Tenta converter volumes (ml, xicara, colher) para ml
                    if unidade_norm_singular in ["ml", "litro", "l", "xicara", "colher", "copo americano"]:
                        fator_ml = 1.0
                        if unidade_norm_singular == "litro" or unidade_norm_singular == "l": fator_ml = 1000.0
                        elif unidade_norm_singular == "xicara": fator_ml = CONVERSOES["xicara_ml"]
                        elif unidade_norm_singular == "copo americano": fator_ml = CONVERSOES["copo_americano_ml"]
                        elif unidade_norm_singular == "colher":
                            # Tenta ser mais específico pela unidade original
                            if "sopa" in unidade_original.lower(): fator_ml = CONVERSOES["colher_sopa_ml"]
                            elif "cha" in unidade_original.lower(): fator_ml = CONVERSOES["colher_cha_ml"]
                            elif "sobremesa" in unidade_original.lower(): fator_ml = CONVERSOES["colher_sobremesa_ml"]
                            else: fator_ml = CONVERSOES["colher_sopa_ml"] # Default
                        ingredientes_agregados[nome_norm_singular]['ml'] += qtde_float * fator_ml

                    # Tenta converter pesos (g, kg) para g
                    elif unidade_norm_singular in ["g", "kg"]:
                        fator_g = 1.0 if unidade_norm_singular == "g" else 1000.0
                        ingredientes_agregados[nome_norm_singular]['g'] += qtde_float * fator_g

                    # Tenta converter saquinhos para g (para arroz)
                    elif unidade_norm_singular == "saquinho" and "arroz" in nome_norm_singular:
                        ingredientes_agregados[nome_norm_singular]['g'] += qtde_float * CONVERSOES["saquinho_arroz_g"]

                    # Unidades contáveis (dente, unidade, folha, fatia, etc.)
                    elif unidade_norm_singular in ["dente", "unidade", "folha", "fatia", "pitada", "gota", "cubo", "raminho"]:
                         ingredientes_agregados[nome_norm_singular][unidade_norm_singular] += qtde_float

                    # Sem unidade, mas com número -> 'unidade'
                    elif not unidade_norm_singular or unidade_norm_singular == 'none':
                        ingredientes_agregados[nome_norm_singular]['unidade'] += qtde_float

                    # Unidade desconhecida com número -> adiciona como descritivo
                    else:
                        desc = f"{quantidade_original} {unidade_original}".strip()
                        if desc and "gosto" not in desc.lower():
                            ingredientes_descritivos[nome_norm_singular].append(desc)

                # --- AGREGAÇÃO DESCRITIVA (Quantidade não numérica) ---
                except (ValueError, TypeError):
                    desc = f"{quantidade_original} {unidade_original}".strip()
                    if desc and "gosto" not in desc.lower() and desc.lower() != "none":
                        # Trata frações como "1/2", "1/4" como 0.5, 0.25 unidades
                        match = re.match(r'(\d+)\s*/\s*(\d+)', str(quantidade_original))
                        if match:
                            num, den = map(int, match.groups())
                            if den != 0:
                                ingredientes_agregados[nome_norm_singular]['unidade'] += num / den
                        else:
                             ingredientes_descritivos[nome_norm_singular].append(desc)


    # --- CONVERSÃO PARA UNIDADES DE COMPRA E FORMATAÇÃO ---
    lista_final_unica = []

    for nome_sing, unidades_dict in sorted(ingredientes_agregados.items()):
        item_str = None
        # --- Lógica de Conversão Específica ---
        if nome_sing == "alho" and "dente" in unidades_dict:
            total_dentes = math.ceil(unidades_dict.pop("dente")) # Arredonda dentes para cima
            if total_dentes > 6:
                cabecas = math.ceil(total_dentes / CONVERSOES["alho_dentes_por_cabeca"])
                unidade_display = singular_para_plural("cabeca", cabecas)
                item_str = f"- Alho: {cabecas} {unidade_display} (aprox.)"
            elif total_dentes > 0:
                 unidade_display = singular_para_plural("dente", total_dentes)
                 item_str = f"- Alho: {int(total_dentes)} {unidade_display}"
            # Se sobrou 'ml' ou 'g' (alho em pó/pasta?), processa genericamente abaixo

        elif nome_sing in ["azeite", "oleo", "shoyu", "vinagre"]: # Líquidos comprados em garrafa
            total_ml = unidades_dict.pop("ml", 0)
            # Tenta converter 'g' para 'ml' (aproximado)
            total_ml += unidades_dict.pop("g", 0) / get_g_per_ml(nome_sing)

            if total_ml > 200: # Se precisar de mais de ~1 xicara, sugere garrafa
                item_str = f"- {nome_sing.capitalize()}: 1 garrafa (aprox.)"
            # Ignora o resto (quantidades pequenas)

        elif nome_sing in ["arroz", "arroz integral", "arroz branco", "arroz japones", "feijao", "lentilha", "grao de bico", "aveia", "farinha de trigo", "farinha de aveia", "farinha de linhaca", "farinha de arroz integral", "proteina de soja texturizada", "acucar", "acucar mascavo", "polvilho", "tapioca", "quinoa"]: # Grãos/Pós
            total_g = unidades_dict.pop("g", 0)
            # Tenta converter 'ml' para 'g' (aproximado)
            total_g += unidades_dict.pop("ml", 0) * get_g_per_ml(nome_sing)
            # Converte unidades (se houver) para gramas
            if "unidade" in unidades_dict and nome_sing == "proteina de soja texturizada": # Caso especial PTS
                 total_g += unidades_dict.pop("unidade") * 60 # Assume 1 unidade = 1 xicara ~ 60g
            elif "unidade" in unidades_dict: # Outros pós/grãos em unidade? Ignora por incerteza
                 unidades_dict.pop("unidade")


            if total_g > 500: # Mais de 500g, converte pra KG
                total_kg = math.ceil(total_g / 500) * 0.5 # Arredonda para 0.5kg mais próximo
                item_str = f"- {nome_sing.capitalize()}: {total_kg:.1f} kg (aprox.)".replace(".0", "")
            elif total_g > 0: # Lista em gramas
                 item_str = f"- {nome_sing.capitalize()}: {int(math.ceil(total_g))} g" # Arredonda gramas para cima

        elif nome_sing in ["cebola", "abobrinha", "pimentao", "batata", "tomate", "limao", "cenoura", "banana", "maca", "pera", "laranja", "mamao", "manga", "berinjela", "abobora", "couve-flor", "brocoli"]: # Contáveis por unidade
            total_unidades = unidades_dict.pop("unidade", 0)
            # Adiciona frações de outras unidades se existirem (ex: 1/2 cebola)
            total_unidades += unidades_dict.pop("fração_unidade", 0) # (Adicionado na agregação)

            # Soma unidades 'dente' se for cebola/alho? Não, alho já tratado.
            # Soma 'fatias' se for pão? Não, pão é complexo (forma, integral...)

            # Ignora 'pedaço'
            unidades_dict.pop("pedaco", None)

            if total_unidades > 0:
                unidades_final = math.ceil(total_unidades) # Arredonda para cima
                unidade_display = singular_para_plural("unidade", unidades_final)
                item_str = f"- {nome_sing.capitalize()}: {unidades_final} {unidade_display}"
            # Ignora o resto (g, ml para esses itens geralmente não é útil para compra)


        # --- Processamento Genérico (Itens não específicos ou unidades restantes) ---
        if not item_str:
            partes_qtde = []
            for unidade_sing, total_qtde in sorted(unidades_dict.items()):
                if not unidade_sing or unidade_sing == 'none' or total_qtde <= 0: continue

                if total_qtde == 0.5: qtde_str = "Meia"
                else: qtde_str = f"{total_qtde:.0f}" if total_qtde == math.ceil(total_qtde) else f"{total_qtde:.2f}".rstrip('0').rstrip('.')

                unidade_display = singular_para_plural(unidade_sing, total_qtde)

                # Omite 'unidade' se for a única unidade e a quantidade for > 0
                if unidade_display in ["unidade", "unidades"] and len(unidades_dict) == 1:
                     partes_qtde.append(f"{qtde_str}")
                else:
                     partes_qtde.append(f"{qtde_str} {unidade_display}".strip())

            if partes_qtde:
                item_str = f"- {nome_sing.capitalize()}: {', '.join(partes_qtde)}"

        if item_str:
            lista_final_unica.append(item_str)

    # Adiciona itens descritivos
    for nome_sing, descricoes in sorted(ingredientes_descritivos.items()):
        # Remove None e duplicatas
        descricoes_validas = sorted(list(set(d for d in descricoes if d and d.lower() != 'none')))
        if descricoes_validas:
            texto_item = f"- {nome_sing.capitalize()}: {', '.join(descricoes_validas)}"
            lista_final_unica.append(texto_item)

    # Ordena a lista final
    return sorted(lista_final_unica, key=lambda x: x.lstrip('- ').lower())


# --- CLASSE PDF (Com estimativa de altura como método) ---
class PDF(FPDF):
    def header(self):
        # (Sem mudanças)
        self.set_font('Arial', 'B', 10)
        # Título um pouco mais abaixo para não colar no topo
        self.set_y(12)
        self.cell(0, 10, 'NutriAI - Seu Plano de Dieta Inteligente', 0, 0, 'C')
        # self.ln(5) # Ln removido do header para controlar espaço na página

    def footer(self):
        # (Sem mudanças)
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

    def safe_cell(self, w, h, text, border, ln, align):
        # (Função de debug)
        cleaned_text = ""
        try:
            cleaned_text = clean_for_pdf(text)
            self.cell(w, h, txt=cleaned_text, border=border, ln=ln, align=align)
        except Exception as e:
            print(f"\n--- DEBUG: ERRO NO SAFE_CELL ---\nTexto Original: {repr(text)}\nTexto Limpo: {repr(cleaned_text)}\nErro: {e}\n")
            raise e

    def safe_multi_cell(self, w, h, text, border=0, align='J', fill=False):
        # Adicionado border, align, fill defaults
        # (Função de debug)
        cleaned_text = ""
        try:
            cleaned_text = clean_for_pdf(text)
            effective_w = w
            if w == 0:
                effective_w = self.w - self.r_margin - self.x
            self.multi_cell(effective_w, h, txt=cleaned_text, border=border, align=align, fill=fill)
        except Exception as e:
            print(f"\n--- DEBUG: ERRO NO SAFE_MULTI_CELL ---\nTexto Original: {repr(text)}\nTexto Limpo: {repr(cleaned_text)}\nErro: {e}\n")
            raise e

    # --- Funções Auxiliares para Layout (Refinadas) ---
    def get_remaining_height(self):
        """Calcula o espaço vertical restante na página atual."""
        return self.h - self.get_y() - self.b_margin # b_margin é a margem inferior

    def estimate_text_height(self, text, width):
        """Estima a altura que um texto ocupará em multi_cell (mais precisa)."""
        if not text: return 0
        cleaned_text = clean_for_pdf(str(text))
        current_font_family = self.font_family
        current_font_style = self.font_style
        current_font_size = self.font_size_pt
        if not self.font_family: self.set_font('Arial', '', 10) # Garante que fonte está definida

        try:
             # Usa line_height diretamente na estimativa
             line_height_mm = self.font_size * 1.2 # Fator 1.2 ~ 1.3 é comum para espaçamento
             lines = self.multi_cell(width, line_height_mm, cleaned_text, split_only=True)
             num_lines = len(lines)
        except Exception as e:
            print(f"WARN: Erro no split_only: {e}. Estimando por comprimento.")
            avg_chars_per_line = width / (self.font_size * 0.6)
            num_lines = math.ceil(len(cleaned_text) / max(1, avg_chars_per_line)) if avg_chars_per_line else 1

        self.set_font(current_font_family, current_font_style, current_font_size)
        estimated_height = num_lines * line_height_mm
        return estimated_height + 3 # Margem de segurança menor (3mm)

    def estimate_recipe_height(self, receita, width):
        """Estima a altura total que uma receita ocupará."""
        current_font = (self.font_family, self.font_style, self.font_size_pt)
        height = 0
        line_h_mult = 1.2 # Multiplicador de altura de linha

        # Título
        self.set_font('Arial', 'B', 14)
        height += self.font_size * line_h_mult + 2 # sub_title approx height + ln(2)
        # Dia sugerido
        if receita.get('dia_sugerido'):
            self.set_font("Arial", 'I', size=9)
            height += self.font_size * line_h_mult + 3 # cell height + ln(3)
        # Header Ingredientes
        self.set_font("Arial", 'B', size=10)
        height += self.font_size * line_h_mult + 2 # cell height + ln(2)
        # Ingredientes Texto
        self.set_font("Arial", size=9)
        ingredientes_texto = ", ".join([ing['descricao'] for ing in receita['ingredientes']])
        height += self.estimate_text_height(ingredientes_texto, width) # Estimate já inclui margem
        # Header Preparo
        self.set_font("Arial", 'B', size=10)
        height += self.font_size * line_h_mult + 2 # cell height + ln(2)
        # Preparo Texto
        self.set_font("Arial", '', 9)
        height += self.estimate_text_height(receita['modo_preparo'], width) # Estimate já inclui margem
        # Espaço final
        height += 8 # ln(8) no final

        self.set_font(current_font[0], current_font[1], current_font[2])
        return height

    def chapter_title(self, title_text):
        # (Sem mudanças)
        self.set_font('Arial', 'B', 18)
        self.safe_cell(0, 10, title_text, 0, 1, 'C')
        self.ln(5)

    def sub_title(self, title_text):
        # (Sem mudanças)
        self.set_font('Arial', 'B', 14)
        self.safe_cell(0, 8, title_text, 0, 1, 'L')
        self.ln(2)


# --- FUNÇÃO PRINCIPAL (LÓGICA DE LAYOUT FINAL++) ---
def criar_pdf_plano_aprimorado(plano_texto: str, receitas_detalhadas: list, user_data: schemas.UserRequestSchema, meta_calorica: float, lista_compras: list):
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15) # Margem inferior para auto break

    available_width = pdf.w - pdf.r_margin - pdf.l_margin

    # --- PÁGINA DE ROSTO E INÍCIO DO PLANO ---
    pdf.set_y(pdf.t_margin) # Garante que começa na margem superior
    pdf.set_font("Arial", 'B', size=24)
    pdf.safe_cell(0, 15, "Seu Plano de Dieta Personalizado", 0, 1, 'C')
    pdf.ln(8)

    pdf.set_font("Arial", 'B', size=14)
    pdf.safe_cell(0, 10, "Resumo do Perfil", 0, 1, 'L')
    pdf.set_font("Arial", size=11)
    perfil_texto = (
        f"Objetivo: {user_data.objetivo.replace('_', ' ').title()}\n"
        f"Meta Calorica Diaria: {meta_calorica:.0f} kcal\n"
        f"Perfil: {user_data.sexo.title()}, {user_data.idade} anos, {user_data.peso_kg}kg, {user_data.altura_cm}cm"
    )
    pdf.safe_multi_cell(available_width, 6, perfil_texto)
    pdf.ln(5)

    # --- PLANO DE REFEIÇÕES (QUEBRA DE PÁGINA INTELIGENTE FINAL) ---
    partes_plano = re.split(r'(#{1,3}\s*.*?)\s*\n', plano_texto) # Captura o título com ###

    # Introdução (antes do primeiro título)
    if partes_plano and len(partes_plano) > 1:
        intro_resumo = partes_plano[0].strip()
        if intro_resumo:
            pdf.set_font('Arial', '', 11)
            altura_intro = pdf.estimate_text_height(intro_resumo, available_width) + 6 # +ln(6)
            if altura_intro > pdf.get_remaining_height():
                pdf.add_page()
                available_width = pdf.w - pdf.r_margin - pdf.l_margin
            pdf.safe_multi_cell(available_width, 6, intro_resumo)
            pdf.ln(6)

    # Loop pelos dias (Título, Corpo)
    for i in range(1, len(partes_plano), 2):
        titulo_dia_raw = partes_plano[i].strip()
        corpo_dia = partes_plano[i+1].strip() if (i+1) < len(partes_plano) else ""

        # Limpa o título (remove ###)
        titulo_dia = re.sub(r'#{1,3}\s*', '', titulo_dia_raw).strip()

        if not titulo_dia: continue

        # --- LÓGICA DE QUEBRA REFINADA ---
        # Estima altura do dia (ln(7) + título + ln(2) + corpo + ln(5))
        altura_titulo = pdf.font_size_pt * 0.352778 * 1.5 + 2 # Aprox. sub_title
        altura_corpo = pdf.estimate_text_height(corpo_dia, available_width)
        altura_total_estimada = 7 + altura_titulo + 2 + altura_corpo + 5 # Soma dos espaçamentos (ln)

        # Se a altura estimada for MAIOR que o espaço restante
        if altura_total_estimada > pdf.get_remaining_height():
             if pdf.get_y() > pdf.t_margin + 5: # Só adiciona página se não estiver já no topo
                pdf.add_page()
                available_width = pdf.w - pdf.r_margin - pdf.l_margin

        # Renderiza o dia
        pdf.ln(7) # Espaçamento ANTES do título (separação do cabeçalho/anterior)
        pdf.sub_title(titulo_dia)
        pdf.set_font('Arial', '', 10)
        pdf.safe_multi_cell(available_width, 6, corpo_dia)
        pdf.ln(5) # Espaçamento DEPOIS do dia

    # --- LISTA DE COMPRAS (COLUNA ÚNICA, QUEBRA POR ITEM REFINADA) ---
    if lista_compras:
        pdf.add_page()
        available_width = pdf.w - pdf.r_margin - pdf.l_margin
        pdf.set_y(pdf.t_margin) # Garante início no topo

        pdf.chapter_title("Lista de Compras Sugerida")
        pdf.set_font("Arial", size=10)

        for item in lista_compras:
            # Estima altura do item + pequeno espaço ln(1)
            altura_item = pdf.estimate_text_height(item, available_width) + 2
            # Se o item NÃO couber no espaço restante
            if altura_item > pdf.get_remaining_height():
                 if pdf.get_y() > pdf.t_margin + 5:
                    pdf.add_page()
                    pdf.set_y(pdf.t_margin) # Garante início no topo
                    available_width = pdf.w - pdf.r_margin - pdf.l_margin

            pdf.safe_multi_cell(available_width, 6, item)
            pdf.ln(1) # Pequeno espaço entre os itens

        pdf.ln(10) # Espaço no final da lista

    # --- DETALHES DAS RECEITAS (QUEBRA DE PÁGINA INTELIGENTE FINAL) ---
    if receitas_detalhadas:
        pdf.add_page()
        available_width = pdf.w - pdf.r_margin - pdf.l_margin
        pdf.set_y(pdf.t_margin) # Garante início no topo

        pdf.chapter_title("Detalhes das Receitas")

        for receita in receitas_detalhadas:
            # Estima altura da receita completa (com margens)
            altura_total_receita = pdf.estimate_recipe_height(receita, available_width) + 15 # Margem extra

            # --- LÓGICA DE QUEBRA REFINADA ---
            # Se a altura estimada for MAIOR que o espaço restante
            if altura_total_receita > pdf.get_remaining_height():
                 if pdf.get_y() > pdf.t_margin + 5: # Evita add_page no topo
                    pdf.add_page()
                    pdf.set_y(pdf.t_margin) # Garante início no topo
                    available_width = pdf.w - pdf.r_margin - pdf.l_margin

            # Renderiza a receita
            pdf.ln(7) # Espaçamento ANTES do título da receita
            pdf.sub_title(receita['titulo'])
            if receita.get('dia_sugerido'):
                pdf.set_font("Arial", 'I', size=9)
                pdf.safe_cell(0, 5, f"(Sugerida para a {receita['dia_sugerido']})", 0, 1, 'L')
                pdf.ln(3)

            pdf.set_font("Arial", 'B', size=10)
            pdf.safe_cell(0, 6, "Ingredientes:", 0, 1, 'L')
            pdf.set_font("Arial", size=9)
            ingredientes_texto = ", ".join([ing.get('descricao', '') for ing in receita.get('ingredientes', [])]) # Mais seguro
            pdf.safe_multi_cell(available_width, 5, ingredientes_texto)
            pdf.ln(2)

            pdf.set_font("Arial", 'B', size=10)
            pdf.safe_cell(0, 6, "Modo de Preparo:", 0, 1, 'L')
            pdf.set_font("Arial", '', 9)
            pdf.safe_multi_cell(available_width, 5, receita.get('modo_preparo', '')) # Mais seguro
            pdf.ln(8) # Espaço maior após cada receita


    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        pdf_path = tmp.name
        pdf.output(pdf_path)
        return pdf_path