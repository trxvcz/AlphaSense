# Dev image — hot reload przez bind-mount w docker-compose.yml.
# Obraz produkcyjny (multi-stage build + `next start`) powstaje w etapie 7.
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
