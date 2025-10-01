# Começamos com a imagem oficial do n8n como base (que usa Alpine Linux)
FROM n8nio/n8n

# Trocamos para o usuário 'root' para poder instalar programas
USER root

# Usamos o comando 'apk' (do Alpine) para adicionar o Docker CLI
RUN apk add --no-cache docker-cli

# Voltamos para o usuário 'node', que é o usuário padrão e mais seguro do n8n
USER node