# NutriAI: Plataforma Inteligente de Nutrição e Receitas

[![Status do Build](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/usuario/nutriai)
[![Licença](https://img.shields.io/badge/license-MIT-blue)](https://github.com/usuario/nutriai/blob/main/LICENSE)

Uma plataforma de dados que utiliza web scraping, LLMs e análise nutricional para criar um banco de dados único de receitas brasileiras, alimentando uma API para aplicações inteligentes e ultra-personalizadas.

## Índice

1.  [Visão Geral do Projeto](#1-visão-geral-do-projeto)
2.  [O Problema a Ser Resolvido](#2-o-problema-a-ser-resolvido)
3.  [A Solução Proposta](#3-a-solução-proposta)
4.  [Arquitetura e Stack Tecnológico](#4-arquitetura-e-stack-tecnológico)
5.  [Instalação e Configuração](#5-instalação-e-configuração)
6.  [Como Usar](#6-como-usar)
7.  [Roadmap de Desenvolvimento](#7-roadmap-de-desenvolvimento)
8.  [Como Contribuir](#8-como-contribuir)

## 1. Visão Geral do Projeto

NutriAI é um sistema de software projetado para transformar a maneira como as pessoas interagem com receitas e nutrição. Ele utiliza web scraping para coletar receitas brasileiras da web, processamento de linguagem natural (LLM) para extrair e estruturar os dados, e análise nutricional para enriquecer cada receita com informações detalhadas. O resultado final é um banco de dados único e poderoso que alimenta uma aplicação inteligente, capaz de oferecer recomendações de refeições ultra-personalizadas, planejamento de cardápios e muito mais.

## 2. O Problema a Ser Resolvido

No cenário atual, ferramentas de receitas e nutrição são fragmentadas e genéricas:

-   **Conteúdo Genérico:** A maioria dos aplicativos usa bases de dados de receitas internacionais, que não refletem a cultura e os ingredientes locais do Brasil.
-   **Falta de Dados Nutricionais:** Receitas online raramente vêm com informações nutricionais precisas, tornando o planejamento de dietas um processo manual e tedioso.
-   **Desperdício de Alimentos:** As pessoas frequentemente não sabem o que cozinhar com os ingredientes que já têm em casa, levando ao desperdício de comida e dinheiro.
-   **Interfaces Pouco Inteligentes:** A busca por receitas ainda é baseada em palavras-chave simples, sem entender o verdadeiro contexto ou preferência do usuário.

## 3. A Solução Proposta

NutriAI resolve esses problemas através de um pipeline de dados automatizado e uma API inteligente.

1.  **Coleta (Scraping):** Um scraper em Python varre fontes populares de receitas brasileiras (TudoGostoso, Panelinha, etc.) para construir um data lake de receitas autênticas.
2.  **Estruturação (LLM Parsing):** Uma Large Language Model (LLM) processa o texto bruto de cada receita, extraindo ingredientes, quantidades, unidades e passos de preparo em um formato JSON estruturado e padronizado.
3.  **Enriquecimento (Nutritional Analysis):** Um script cruza os ingredientes extraídos com a **Tabela Brasileira de Composição de Alimentos (TACO)** para calcular, com alta precisão, o perfil nutricional completo de cada prato (calorias, proteínas, gorduras, carboidratos).
4.  **Serviço (API):** Uma API RESTful expõe essa base de dados enriquecida, permitindo que aplicações (web, mobile) façam consultas complexas e inteligentes.

## 4. Arquitetura e Stack Tecnológico

-   **Linguagem:** Python
-   **Coleta de Dados:** Scrapy / BeautifulSoup, Cloudscraper
-   **Processamento de Dados:** Pandas, spaCy (para NLP auxiliar)
-   **Inteligência Artificial:** APIs do Google Gemini ou OpenAI (GPT-4)
-   **Banco de Dados Nutricional:** Tabela TACO (processada)
-   **Banco de Dados Principal:** PostgreSQL ou MongoDB
-   **API:** FastAPI
-   **Infraestrutura:** Docker, com potencial deploy em Render, Heroku ou AWS/GCP.

## 5. Instalação e Configuração

Para executar este projeto localmente, siga os passos abaixo:

1.  **Clone o repositório:**
    ```bash
    git clone [https://github.com/seu-usuario/nutriai.git](https://github.com/seu-usuario/nutriai.git)
    cd nutriai
    ```

2.  **Crie e ative um ambiente virtual:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # No Windows, use `venv\Scripts\activate`
    ```

3.  **Instale as dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure as variáveis de ambiente:**
    - Renomeie o arquivo `.env.example` para `.env`.
    - Preencha as variáveis necessárias, como chaves de API (OpenAI/Gemini) e credenciais do banco de dados.

## 6. Como Usar

Após a instalação, você pode executar os diferentes módulos do projeto.

-   **Para iniciar a API:**
    ```bash
    uvicorn app.main:app --reload
    ```
    Acesse a documentação interativa em `http://127.0.0.1:8000/docs`.

-   **Para executar o scraper:**
    ```bash
    python scripts/run_scraper.py --site tudogostoso --pages 10
    ```

## 7. Roadmap de Desenvolvimento

### Fase 1: Fundação de Dados (MVP) - (Foco Atual)
O objetivo desta fase é construir o ativo principal: a base de dados.

-   [x] Limpeza da Base Nutricional: Processar e limpar a Tabela TACO.
-   [ ] Desenvolvimento do Scraper: Criar um scraper para ao menos um grande portal de receitas.
-   [ ] Desenvolvimento do Pipeline de Enriquecimento:
    -   [ ] Criar o script que usa a LLM para extrair ingredientes.
    -   [ ] Criar o script que calcula os valores nutricionais com base na Tabela TACO.
-   [ ] API Básica: Criar um endpoint simples para consultar as receitas processadas.

### Fase 2: Módulos de Inteligência (Recursos Futuros)
Com a fundação pronta, o projeto pode evoluir com os seguintes módulos:

#### Módulo 1: Desperdício Zero ♻️
-   **Funcionalidade:** O usuário informa os ingredientes que tem na geladeira e o sistema gera um plano de refeições para a semana, maximizando o uso desses itens e minimizando o desperdício.
-   **Diferencial:** Apelo econômico e ecológico direto.

#### Módulo 2: Paladar Personalizado (Flavor DNA) 🧬
-   **Funcionalidade:** O sistema aprende o perfil de sabor do usuário (picante, ácido, cremoso) e recomenda receitas com base na compatibilidade de paladar.
-   **Diferencial:** Hiper-personalização que cria uma conexão emocional com o usuário.

#### Módulo 3: Planejador Contextual 🧠
-   **Funcionalidade:** Conecta-se a dados externos (calendário, clima) para fazer sugestões proativas. Ex: "Dia frio, que tal uma sopa de lentilhas?".
-   **Diferencial:** Transforma o app de uma ferramenta reativa para um assistente proativo.

## 8. Como Contribuir

Contribuições são bem-vindas! Se você tem ideias para melhorias ou encontrou algum bug, sinta-se à vontade para:

1.  Fazer um "Fork" do projeto.
2.  Criar uma nova "Branch" (`git checkout -b feature/sua-feature`).
3.  Fazer o "Commit" das suas alterações (`git commit -m 'Adiciona nova feature'`).
4.  Fazer o "Push" para a Branch (`git push origin feature/sua-feature`).
5.  Abrir um "Pull Request".
