# 1. Imagem Base: Começamos com uma imagem oficial do Python.
# A versão 'slim' é menor e ideal para produção.
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Diretório de Trabalho: Define o diretório onde nossa aplicação vai ficar dentro do contêiner.
WORKDIR /app

# 4. Copiar e Instalar Dependências:
# Copiamos APENAS o requirements.txt primeiro. O Docker funciona em camadas,
# então ele só vai reinstalar as dependências se este arquivo mudar.
COPY requirements.txt .

# Rodamos o pip install para baixar e instalar tudo.
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiar o Código-Fonte: Agora copiamos todo o resto do seu projeto para o diretório /app.
COPY . .

# 6. Comando para Manter o Contêiner Rodando:
# Seus scripts são de execução pontual. Para que o n8n (no futuro) ou nós mesmos 
# possamos executá-los, o contêiner precisa ficar "vivo". Este comando simplesmente
# mantém o contêiner rodando sem fazer nada.
CMD ["tail", "-f", "/dev/null"]