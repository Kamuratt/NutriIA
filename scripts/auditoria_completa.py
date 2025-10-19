# scripts/auditoria_completa.py
import os
import json
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
import collections # Para contar os problemas

# --- CONFIGURAÇÃO ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path, encoding='utf-8')

# Frases problemáticas conhecidas no modo_preparo
FRASES_PROBLEMATICAS_PREPARO = [
    '%hello%',
    '%how can i help%',
    '%how may i assist%',
    '%não é possível corrigi-lo%',
    '%não pode ser convertido%'
]

# --- FUNÇÃO AUXILIAR DE NORMALIZAÇÃO ---
def normalizar_texto(texto: str) -> str:
    if not texto or not isinstance(texto, str): return ""
    try: return texto.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        try: return texto.encode('utf-8', 'ignore').decode('utf-8')
        except Exception: return texto

def auditar_dados_receitas():
    """Conecta ao banco e realiza uma auditoria completa na tabela de receitas."""
    try:
        db_url = URL.create(
            drivername="postgresql+psycopg2", username=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST"),
            port=os.getenv("POSTGRES_PORT"), database=os.getenv("POSTGRES_DB"),
            query={"client_encoding": "utf8"}
        )
        engine = create_engine(db_url)
        print("✔️ Conectado ao PostgreSQL.")
    except Exception as e:
        print(f"❌ ERRO ao conectar ao PostgreSQL: {e}"); return

    print("\nIniciando auditoria completa da tabela 'receitas'...")

    problemas_encontrados = collections.defaultdict(list)
    total_receitas = 0

    try:
        with engine.connect() as conn:
            query = text("""
                SELECT id, titulo, url, ingredientes_brutos, modo_preparo,
                       processado_pela_llm, ingredientes,
                       nutrientes_calculados, informacoes_nutricionais, revisado
                FROM receitas ORDER BY id;
            """)
            resultado = conn.execute(query).fetchall()
            total_receitas = len(resultado)
            print(f"Encontradas {total_receitas} receitas para auditar.")

            for i, row in enumerate(resultado):
                if (i + 1) % 500 == 0:
                    print(f"   ... {i+1} receitas auditadas.")

                # --- Verificações ---
                # (Verificações 1 a 5 sem alterações)
                # 1. Título
                if not row.titulo: problemas_encontrados['titulo_vazio'].append(row.id)
                elif normalizar_texto(row.titulo) != row.titulo: problemas_encontrados['titulo_encoding'].append(row.id)
                # 2. URL
                if not row.url: problemas_encontrados['url_vazio'].append(row.id)
                # 3. Ingredientes Brutos
                if not row.ingredientes_brutos: problemas_encontrados['ingredientes_brutos_vazio'].append(row.id)
                # 4. Modo de Preparo
                if not row.modo_preparo: problemas_encontrados['modo_preparo_vazio'].append(row.id)
                elif normalizar_texto(row.modo_preparo) != row.modo_preparo: problemas_encontrados['modo_preparo_encoding'].append(row.id)
                else:
                    for frase in FRASES_PROBLEMATICAS_PREPARO:
                        if frase.strip('%') in row.modo_preparo.lower():
                            problemas_encontrados['modo_preparo_frase_problematica'].append(row.id)
                            break
                # 5. Consistência: processado_pela_llm vs ingredientes
                if row.processado_pela_llm and not row.ingredientes: problemas_encontrados['llm_true_sem_ingredientes'].append(row.id)
                if not row.processado_pela_llm and row.ingredientes: problemas_encontrados['llm_false_com_ingredientes'].append(row.id)

                # --- CORREÇÃO AQUI ---
                # 6. Validade JSON e conteúdo de 'ingredientes'
                ing_list = None
                if row.ingredientes:
                    try:
                        # Verifica se já é uma lista/dict (SQLAlchemy já processou)
                        if isinstance(row.ingredientes, (list, dict)):
                            ing_list = row.ingredientes
                        # Se for string, tenta carregar como JSON
                        elif isinstance(row.ingredientes, str):
                             ing_list = json.loads(row.ingredientes)
                        else:
                             problemas_encontrados['ingredientes_tipo_inesperado'].append(row.id)

                        if ing_list is not None:
                            if not isinstance(ing_list, list): problemas_encontrados['ingredientes_nao_lista'].append(row.id)
                            elif not ing_list: problemas_encontrados['ingredientes_lista_vazia'].append(row.id)
                            else:
                                for ing in ing_list:
                                    if not isinstance(ing, dict) or 'nome_ingrediente' not in ing or not ing['nome_ingrediente']:
                                        problemas_encontrados['ingrediente_sem_nome'].append(row.id)
                                        break
                                    if 'texto_original' not in ing:
                                         problemas_encontrados['ingrediente_sem_texto_original'].append(row.id)
                                         break
                                    elif normalizar_texto(ing.get('texto_original','')) != ing.get('texto_original',''):
                                         problemas_encontrados['ingrediente_texto_original_encoding'].append(row.id)
                                         break
                    except json.JSONDecodeError:
                        problemas_encontrados['ingredientes_json_invalido'].append(row.id)
                # --- FIM DA CORREÇÃO 6 ---

                # 7. Consistência: nutrientes_calculados vs informacoes_nutricionais (sem alterações)
                if row.nutrientes_calculados and not row.informacoes_nutricionais: problemas_encontrados['calc_true_sem_info'].append(row.id)
                if not row.nutrientes_calculados and row.informacoes_nutricionais: problemas_encontrados['calc_false_com_info'].append(row.id)

                # --- CORREÇÃO AQUI ---
                # 8. Validade JSON de 'informacoes_nutricionais'
                info_dict = None
                if row.informacoes_nutricionais:
                    try:
                        # Verifica se já é um dict
                        if isinstance(row.informacoes_nutricionais, dict):
                            info_dict = row.informacoes_nutricionais
                        # Se for string, tenta carregar como JSON
                        elif isinstance(row.informacoes_nutricionais, str):
                            info_dict = json.loads(row.informacoes_nutricionais)
                        else:
                             problemas_encontrados['info_nutri_tipo_inesperado'].append(row.id)

                        if info_dict is not None and not isinstance(info_dict, dict):
                             problemas_encontrados['info_nutri_nao_dict'].append(row.id)
                    except json.JSONDecodeError:
                        problemas_encontrados['info_nutri_json_invalido'].append(row.id)
                # --- FIM DA CORREÇÃO 8 ---

                # 9. Verificação pós-revisão (sem alterações)
                if row.revisado:
                    if normalizar_texto(row.titulo) != row.titulo: problemas_encontrados['revisado_com_titulo_encoding'].append(row.id)
                    if normalizar_texto(row.modo_preparo) != row.modo_preparo: problemas_encontrados['revisado_com_preparo_encoding'].append(row.id)
                    for frase in FRASES_PROBLEMATICAS_PREPARO:
                         if frase.strip('%') in row.modo_preparo.lower():
                            problemas_encontrados['revisado_com_frase_problematica'].append(row.id)
                            break
                    if ing_list: # Reusa a lista já processada no passo 6
                         for ing in ing_list:
                             if normalizar_texto(ing.get('texto_original','')) != ing.get('texto_original',''):
                                 problemas_encontrados['revisado_com_ingrediente_encoding'].append(row.id)
                                 break

    except Exception as e:
        print(f"\n❌ ERRO durante a auditoria: {e}")
        import traceback
        traceback.print_exc() # Imprime o stack trace completo para depuração
    finally:
        if engine: engine.dispose()

    # --- Relatório Final (sem alterações) ---
    print("\n" + "="*80)
    print("= RELATÓRIO DA AUDITORIA COMPLETA DE DADOS".center(80))
    print("="*80)
    print(f"Total de Receitas Verificadas: {total_receitas}")

    if not problemas_encontrados:
        print("\n✅ Nenhuma inconsistência grave encontrada!")
    else:
        print("\n⚠️ Inconsistências Encontradas:")
        for tipo, ids in sorted(problemas_encontrados.items()): # Ordenado para melhor leitura
            count = len(ids)
            percent = (count / total_receitas) * 100 if total_receitas else 0
            print(f"  - {tipo}: {count} receitas ({percent:.2f}%)")
            if count > 0:
                print(f"    (Exemplos de IDs: {ids[:5]}{'...' if count > 5 else ''})")

    print("\n[!] PRÓXIMOS PASSOS RECOMENDADOS:")
    if problemas_encontrados.get('revisado_com_frase_problematica') or problemas_encontrados.get('revisado_com_preparo_encoding') or problemas_encontrados.get('revisado_com_ingrediente_encoding') or problemas_encontrados.get('revisado_com_titulo_encoding'):
        print("    1. Resetar o status 'revisado' das receitas problemáticas (UPDATE receitas SET revisado = FALSE WHERE id IN (...)).")
        print("    2. Rodar novamente 'revisar_receitas_processadas.py' para corrigi-las.")
    if problemas_encontrados.get('ingrediente_sem_nome') or problemas_encontrados.get('ingredientes_json_invalido') or problemas_encontrados.get('ingrediente_sem_texto_original'):
         print("    3. Investigar por que o script 'enriquecer_dados.py' (ou similar) está gerando/salvando JSONs inválidos ou incompletos.")
         print("       -> Considere rodar 'auditoria_dados.py' para limpar ingredientes inválidos antes de calcular nutrientes.")
    if problemas_encontrados.get('calc_true_sem_info') or problemas_encontrados.get('info_nutri_json_invalido'):
         print("    4. Investigar e possivelmente rodar novamente 'calcular_nutrientes.py' para as receitas afetadas.")
    if not problemas_encontrados:
         print("    - A qualidade dos dados parece boa. Considere rodar 'calcular_nutrientes.py' se houver receitas não calculadas.")

    print("="*80)
    print("\nAuditoria finalizada.")

if __name__ == "__main__":
    auditar_dados_receitas()