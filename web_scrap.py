import json
import re
import os
import time  # Importe a biblioteca time
import random # Importe a biblioteca random para pausas mais naturais
import cloudscraper
from bs4 import BeautifulSoup

def buscar_links_receitas(termo: str, paginas: int = 1) -> list[str]:
    """Busca links de receitas pelo termo informado no TudoGostoso."""
    links = []
    scraper = cloudscraper.create_scraper()

    print(f"Buscando por '{termo}' em {paginas} página(s)...")
    for page in range(1, paginas + 1):
        termo_url = re.sub(r'\s+', '%20', termo)
        url_busca = f"https://www.tudogostoso.com.br/busca?search={termo_url}&page={page}"
        
        print(f"Acessando página de busca: {url_busca}")
        
        try:
            resp = scraper.get(url_busca)
            if resp.status_code != 200:
                print(f"Erro ao acessar página {page}. Status: {resp.status_code}")
                continue
        except Exception as e:
            print(f"Ocorreu uma exceção ao tentar acessar a página {page}: {e}")
            continue

        soup = BeautifulSoup(resp.content, 'html.parser')
        
        # --- LINHA CORRIGIDA COM O SELETOR CERTO ---
        links_encontrados = soup.select(".card-recipe .card-link")

        if not links_encontrados:
            print(f"Nenhum link de receita encontrado na página {page}. Verifique o HTML ou o seletor.")
            break 

        for a in links_encontrados:
            href = a.get("href")
            # A URL já vem completa no HTML que recebemos
            if href:
                links.append(href)
        
        time.sleep(random.uniform(1, 3)) 

    return list(dict.fromkeys(links))


def scrape_receita(url: str, scraper) -> dict:
    """Faz scraping de uma receita do TudoGostoso e retorna um dicionário estruturado"""
    print(f"Acessando {url}...")
    pagina = scraper.get(url)

    if pagina.status_code != 200:
        print("Erro ao acessar:", pagina.status_code)
        return {}

    soup = BeautifulSoup(pagina.content, 'html.parser')

    # título
    titulo = soup.find('h1').get_text(strip=True)

    # ingredientes
    ingredientes = [span.get_text(strip=True)
                    for span in soup.select('.recipe-ingredients-item-label')]

    # modo de preparo (duas tentativas de seletor)
    modo_preparo = [li.get_text(strip=True)
                    for li in soup.select('.instructions.e-instructions li')]
    if not modo_preparo:
        modo_preparo = [p.get_text(strip=True)
                        for p in soup.select('.recipe-steps-text p')]

    receita = {
        "titulo": titulo,
        "ingredientes": ingredientes,
        "modo_preparo": modo_preparo
    }

    return receita

def salvar_receita_json(receita: dict, pasta: str = "receitas"):
    """Salva uma receita em arquivo JSON dentro de uma pasta"""
    if not receita:
        return
    
    os.makedirs(pasta, exist_ok=True)
    
    # Nome de arquivo seguro
    nome_arquivo = re.sub(r'[\\/*?:"<>|]', "", receita["titulo"])
    nome_arquivo = re.sub(r'[^a-zA-Z0-9_-]', '_', nome_arquivo) + ".json"
    
    caminho = os.path.join(pasta, nome_arquivo)
    
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(receita, f, ensure_ascii=False, indent=4)
    print(f"Arquivo '{caminho}' salvo com sucesso!")



scraper_global = cloudscraper.create_scraper()

    # Defina o termo e o número de páginas que deseja buscar
TERMO_DE_BUSCA = "fitness"
NUMERO_DE_PAGINAS = 10 # Busque em 2 páginas de resultados, por exemplo

links_das_receitas = buscar_links_receitas(TERMO_DE_BUSCA, paginas=NUMERO_DE_PAGINAS)

if links_das_receitas:
    # ...
    for link in links_das_receitas:
        receita_extraida = scrape_receita(link, scraper_global)
        salvar_receita_json(receita_extraida)
        # Pausa entre a extração de cada receita
        time.sleep(random.uniform(1, 2))
else: # Este else pertence ao 'if'
    print("Nenhum link de receita foi encontrado para o termo informado.")

    print("\nProcesso finalizado!")