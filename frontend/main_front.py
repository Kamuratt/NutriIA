# frontend/main_front.py
import streamlit as st
import requests
import json

# Define o título da página e o ícone que aparecerão na aba do navegador
st.set_page_config(page_title="NutriAI", page_icon="🍎")

# URL da nossa API FastAPI que está rodando
API_URL = "http://127.0.0.1:8000/planejar-dieta/"

# --- Dicionários de Mapeamento (A TRADUÇÃO) ---
# Mapeia o que o usuário vê para o que a API espera
# --- CORREÇÃO APLICADA AQUI ---
sexo_map = {"Masculino": "masculino", "Feminino": "feminino"}
atividade_map = {"Sedentario": "sedentario", "Leve": "leve", "Moderado": "moderado", "Ativo": "ativo"}
objetivo_map = {"Perder Peso": "perder_peso", "Manter Peso": "manter_peso", "Ganhar Massa": "ganhar_massa"}


# --- Interface Gráfica ---

st.title("🍎 NutriAI: Planejador de Dietas Inteligente")
st.markdown("Preencha seus dados abaixo e receba um plano de refeições personalizado, gerado por IA com base em receitas brasileiras!")

# Usamos um formulário para agrupar os inputs e ter um único botão de envio
with st.form(key="user_form"):
    st.subheader("Sobre você")

    # Divide a tela em duas colunas para melhor organização
    col1, col2 = st.columns(2)
    with col1:
        # As opções aqui são amigáveis para o usuário
        sexo_selecionado = st.radio("Sexo:", ('Masculino', 'Feminino'), horizontal=True)
        idade = st.number_input("Idade:", min_value=1, max_value=120, value=30, step=1)
        peso_kg = st.number_input("Peso (kg):", min_value=1.0, value=70.0, step=0.5, format="%.1f")
        altura_cm = st.number_input("Altura (cm):", min_value=1.0, value=175.0, step=0.5, format="%.1f")

    with col2:
        atividade_selecionada = st.selectbox(
            "Nível de Atividade Física:",
            ('Sedentario', 'Leve', 'Moderado', 'Ativo'),
            index=2  # Define 'Moderado' como o valor padrão
        )
        objetivo_selecionado = st.selectbox(
            "Qual seu objetivo?",
            ('Perder Peso', 'Manter Peso', 'Ganhar Massa'),
            index=1  # Define 'Manter Peso' como o valor padrão
        )

    # Botão de envio do formulário
    submit_button = st.form_submit_button(label="Gerar meu Plano de Dieta ✨")

# --- Lógica de chamada da API ---
if submit_button:
    # --- AQUI ACONTECE A NORMALIZAÇÃO ---
    # Traduz as seleções do usuário para o formato da API usando os dicionários
    sexo_para_api = sexo_map[sexo_selecionado]
    atividade_para_api = atividade_map[atividade_selecionada]
    objetivo_para_api = objetivo_map[objetivo_selecionado]

    # Monta o dicionário com os dados já traduzidos
    user_data = {
        "peso_kg": peso_kg,
        "altura_cm": altura_cm,
        "idade": idade,
        "sexo": sexo_para_api,
        "nivel_atividade": atividade_para_api,
        "objetivo": objetivo_para_api
    }

    # Mostra uma mensagem de "carregando" enquanto espera a resposta da API
    with st.spinner("Calculando sua meta calórica e consultando a IA... Isso pode levar alguns segundos."):
        try:
            # Faz a requisição POST para a API, enviando os dados em formato JSON
            response = requests.post(API_URL, data=json.dumps(user_data))

            # Verifica se a API retornou um código de sucesso (200)
            if response.status_code == 200:
                result = response.json()
                st.success("Plano de dieta gerado com sucesso!")
                
                # Exibe os resultados formatados
                st.subheader("Sua Meta Calórica Calculada")
                st.info(f"**{result['meta_calorica_calculada']:.0f} kcal por dia**")

                st.subheader("Sugestão de Plano de Refeições")
                st.markdown(result['plano_texto'])

            else:
                # Se a API retornar um erro, mostra uma mensagem clara
                st.error(f"Ocorreu um erro na API. (Código: {response.status_code})")
                st.json(response.json()) # Mostra o detalhe do erro retornado pela API

        except requests.exceptions.RequestException as e:
            # Se não conseguir nem se conectar à API, mostra esta mensagem
            st.error(f"Não foi possível conectar à API. Verifique se o backend (Uvicorn) está rodando. Erro: {e}")