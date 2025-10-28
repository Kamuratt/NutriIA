import streamlit as st
import requests
import json
import os

st.set_page_config(page_title="NutriAI", page_icon="🍎", layout="wide")

# Lê a URL BASE da API do ambiente Docker.
# O valor padrão agora reflete a porta 8085 que funciona na sua máquina local.
BASE_API_URL = os.getenv("API_URL", "http://127.0.0.1:8085")

DIETA_ENDPOINT = "/planejar-dieta/"


sexo_map = {"Masculino": "masculino", "Feminino": "feminino"}
atividade_map = {"Sedentário": "sedentario", "Leve": "leve", "Moderado": "moderado", "Ativo": "ativo"}
objetivo_map = {"Perder Peso": "perder_peso", "Manter Peso": "manter_peso", "Ganhar Massa": "ganhar_massa"}

restricao_map = {
    "Vegetariano": "vegetariano",
    "Vegano": "vegano",
    "Sem Glúten (Celíaco)": "sem_gluten",
    "Sem Lactose": "sem_lactose",
    "Sem Oleaginosas (castanhas, nozes)": "sem_oleaginosas",
    "Sem Frutos do Mar": "sem_frutos_do_mar",
    "Sem Ovos": "sem_ovo",
    "Sem Soja": "sem_soja"
}

st.title("🍎 NutriAI: Planejador de Dietas Inteligente")
st.markdown("Preencha seus dados abaixo e receba um plano de refeições personalizado, gerado por IA com base em receitas brasileiras!")

with st.form(key="user_form"):
    st.subheader("Sobre você")

    col1, col2, col3 = st.columns(3)
    with col1:
        sexo_selecionado = st.radio("Sexo:", ('Masculino', 'Feminino'), horizontal=True)
        idade = st.number_input("Idade:", min_value=1, max_value=120, step=1, value=None, placeholder="Sua idade...")

    with col2:
        peso_kg = st.number_input("Peso (kg):", min_value=1.0, step=0.5, format="%.1f", value=None, placeholder="Seu peso...")
        altura_cm = st.number_input("Altura (cm):", min_value=1.0, step=0.5, format="%.1f", value=None, placeholder="Sua altura...")

    with col3:
        atividade_selecionada = st.selectbox("Nível de Atividade Física:", list(atividade_map.keys()), index=None, placeholder="Selecione seu nível...")
        objetivo_selecionado = st.selectbox("Qual seu objetivo?", list(objetivo_map.keys()), index=None, placeholder="Selecione seu objetivo...")

    st.subheader("Saúde e Bem-estar (Opcional)")
    col_saude1, col_saude2 = st.columns(2)
    with col_saude1:
        doencas_cronicas = st.multiselect(
            "Você possui alguma condição abaixo?",
            ["Hipertensão", "Diabetes Tipo 2"],
            placeholder="Selecione, se aplicável"
        )
    with col_saude2:
        circunferencia_cintura = st.number_input(
            "Circunferência da cintura (cm):",
            min_value=30.0, step=0.5, format="%.1f", value=None,
            placeholder="Opcional, mas ajuda na avaliação",
            help="Medir na altura do umbigo. Ajuda a avaliar riscos metabólicos."
        )

    st.subheader("Duração do Plano")
    tipo_plano_selecionado = st.radio(
        "Selecione a duração:",
        ('Semanal (7 dias)', 'Mensal (4 semanas)'),
        horizontal=True,
        label_visibility="collapsed"
    )

    st.subheader("Restrições Alimentares (Opcional)")
    restricoes_selecionadas = st.multiselect(
        "Selecione uma ou mais restrições:",
        options=list(restricao_map.keys()),
        label_visibility="collapsed"
    )

    submit_button = st.form_submit_button(label="Gerar meu Plano de Dieta ✨")

if submit_button:
    # Validação dos campos obrigatórios
    campos_obrigatorios = {
        'Idade': idade,
        'Peso': peso_kg,
        'Altura': altura_cm,
        'Nível de Atividade': atividade_selecionada,
        'Objetivo': objetivo_selecionado
    }
    campos_faltando = [nome for nome, valor in campos_obrigatorios.items() if valor is None]

    if campos_faltando:
        st.error(f"Por favor, preencha os seguintes campos obrigatórios: {', '.join(campos_faltando)}")
    else:
        tipo_plano_api = "mensal" if "Mensal" in tipo_plano_selecionado else "semanal"
        
        # Nota: Os novos campos (doencas_cronicas, circunferencia_cintura) ainda não são enviados para a API.
        # Adicionaremos isso quando o backend estiver pronto para recebê-los.
        user_data = {
            "peso_kg": peso_kg,
            "altura_cm": altura_cm,
            "idade": idade,
            "sexo": sexo_map[sexo_selecionado],
            "nivel_atividade": atividade_map[atividade_selecionada],
            "objetivo": objetivo_map[objetivo_selecionado],
            "restricoes": [restricao_map[r] for r in restricoes_selecionadas],
            "tipo_plano": tipo_plano_api
        }

        with st.spinner(f"Gerando seu plano {tipo_plano_api}... Isso pode demorar alguns minutos."):
            try:
                full_api_url = f"{BASE_API_URL}{DIETA_ENDPOINT}"
                
                response = requests.post(full_api_url, data=json.dumps(user_data))

                if response.status_code == 200:
                    st.success("Seu plano de dieta personalizado está pronto!")
                    
                    st.download_button(
                        label="Baixar meu Plano de Dieta (PDF) ⬇️",
                        data=response.content,
                        file_name=f"Plano_NutriAI_{tipo_plano_api}.pdf",
                        mime="application/pdf"
                    )
                else:
                    st.error(f"Ocorreu um erro na API. (Código: {response.status_code})")
                    try:
                        st.json(response.json())
                    except json.JSONDecodeError:
                        st.text(response.text)

            except requests.exceptions.RequestException as e:
                st.error(f"Não foi possível conectar à API. Verifique se o backend (Uvicorn) está rodando. Erro: {e}")