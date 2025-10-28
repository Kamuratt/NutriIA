FROM n8nio/n8n

# Trocamos para o usuário 'root' para poder instalar os pacotes do sistema
USER root

# Instalar o Docker CLI e o Docker Compose v2 diretamente pelo apk.
# Isso é mais limpo e estável do que usar o pip para esta finalidade.
RUN apk add --no-cache docker-cli docker-compose

# SÓ DEPOIS da instalação, voltamos para o usuário 'node' por segurança
USER node