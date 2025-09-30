# frontend/main_front.py
import streamlit as st
import requests
import json

st.set_page_config(page_title="NutriAI", page_icon="🍎", layout="wide")

API_URL = "http://127.0.0.1:8000/planejar-dieta/"

# --- DICIONÁRIOS DE MAPEAMENTO ---
sexo_map = {"Masculino": "masculino", "Feminino": "feminino"}
atividade_map = {"Sedentário": "sedentario", "Leve": "leve", "Moderado": "moderado", "Ativo": "ativo"}
objetivo_map = {"Perder Peso": "perder_peso", "Manter Peso": "manter_peso", "Ganhar Massa": "ganhar_massa"}
# Adicionamos o dicionário para as restrições
restricao_map = {
    "Vegetariano": "vegetariano",
    "Vegano": "vegano",
    "Sem Glúten (Celíaco)": "sem_gluten",
    "Sem Lactose": "sem_lactose"
}


st.title("🍎 NutriAI: Planejador de Dietas Inteligente")
st.markdown("Preencha seus dados abaixo e receba um plano de refeições personalizado, gerado por IA com base em receitas brasileiras!")

with st.form(key="user_form"):
    st.subheader("Sobre você")

    col1, col2, col3 = st.columns(3)
    with col1:
        sexo_selecionado = st.radio("Sexo:", ('Masculino', 'Feminino'), horizontal=True)
        idade = st.number_input("Idade:", min_value=1, max_value=120, value=30, step=1)
    
    with col2:
        peso_kg = st.number_input("Peso (kg):", min_value=1.0, value=70.0, step=0.5, format="%.1f")
        altura_cm = st.number_input("Altura (cm):", min_value=1.0, value=175.0, step=0.5, format="%.1f")

    with col3:
        # Usamos list(dict.keys()) para popular as opções dinamicamente
        atividade_selecionada = st.selectbox("Nível de Atividade Física:", list(atividade_map.keys()), index=2)
        objetivo_selecionado = st.selectbox("Qual seu objetivo?", list(objetivo_map.keys()), index=1)

    # --- CAMPO DE RESTRIÇÕES ADICIONADO AQUI ---
    st.subheader("Restrições Alimentares (Opcional)")
    restricoes_selecionadas = st.multiselect(
        "Selecione uma ou mais restrições:",
        options=list(restricao_map.keys()),
        label_visibility="collapsed" # Esconde o rótulo principal para um visual mais limpo
    )

    submit_button = st.form_submit_button(label="Gerar meu Plano de Dieta ✨")

if submit_button:
    # Traduz TODAS as seleções para o formato da API
    sexo_para_api = sexo_map[sexo_selecionado]
    atividade_para_api = atividade_map[atividade_selecionada]
    objetivo_para_api = objetivo_map[objetivo_selecionado]
    # Converte a lista de seleções de restrições para o formato da API
    restricoes_para_api = [restricao_map[r] for r in restricoes_selecionadas]

    user_data = {
        "peso_kg": peso_kg,
        "altura_cm": altura_cm,
        "idade": idade,
        "sexo": sexo_para_api,
        "nivel_atividade": atividade_para_api,
        "objetivo": objetivo_para_api,
        "restricoes": restricoes_para_api # Envia a lista de restrições
    }

    with st.spinner("Calculando sua meta calórica e consultando a IA... Isso pode levar alguns segundos."):
        try:
            response = requests.post(API_URL, data=json.dumps(user_data))

            if response.status_code == 200:
                result = response.json()
                st.success("Plano de dieta gerado com sucesso!")
                
                st.subheader("Sua Meta Calórica Calculada")
                st.info(f"**{result['meta_calorica_calculada']:.0f} kcal por dia**")

                st.subheader("Sugestão de Plano de Refeições")
                st.markdown(result['plano_texto'])
                
                if result.get('receitas_detalhadas'):
                    st.subheader("Detalhes das Receitas Sugeridas")
                    for receita in result['receitas_detalhadas']:
                        with st.expander(f"🍽️ {receita['titulo']}"):
                            st.markdown("**Ingredientes:**")
                            for ingrediente in receita['ingredientes']:
                                st.markdown(f"- {ingrediente['descricao']}")
                            
                            st.markdown("\n**Modo de Preparo:**")
                            st.text(receita['modo_preparo'])
            else:
                st.error(f"Ocorreu um erro na API. (Código: {response.status_code})")
                st.json(response.json())

        except requests.exceptions.RequestException as e:
            st.error(f"Não foi possível conectar à API. Verifique se o backend (Uvicorn) está rodando. Erro: {e}")