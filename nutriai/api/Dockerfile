# Use uma imagem base do Python.
FROM python:3.10-slim

# Defina o diretório de trabalho.
WORKDIR /app

# 1. Copia o arquivo de dependências da sua estrutura de pastas para a raiz do WORKDIR.
COPY ./nutriai/api/requirements.txt .

# Instale as dependências.
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copia a pasta 'nutriai' inteira (que contém a 'api') para dentro do WORKDIR.
# Isso garante que a estrutura de pacotes seja mantida dentro do container.
COPY ./nutriai /app/nutriai

# O comando para iniciar será dado pelo docker-compose.yml, então não precisamos de CMD aqui.
# O expose continua sendo uma boa prática.
EXPOSE 8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
