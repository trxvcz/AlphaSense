# Obraz wielostopniowy: `dev` (hot reload) i `prod` (build standalone,
# użytkownik nie-root). Stopień wybiera compose przez `target:` —
# `docker-compose.yml` → dev, `docker-compose.prod.yml` → prod.

FROM node:22-slim AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci


FROM deps AS dev

# Kod i tak jest przykryty bind-mountem z compose; kopiowany, żeby obraz
# dało się uruchomić samodzielnie (np. `docker run` przy diagnostyce).
COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]


FROM deps AS build

# UWAGA: `NEXT_PUBLIC_*` są WYPIEKANE w bundle na etapie `next build` — nie
# da się ich nadpisać zmienną środowiskową w compose po zbudowaniu obrazu.
# Stąd `ARG`, nie `environment:`.
#
# Domyślne `/api` to adres WZGLĘDNY: w produkcji Caddy serwuje frontend i API
# z tego samego origin, więc przeglądarka trafia pod `https://<domena>/api/...`
# bez CORS-a. Działa, bo żaden Server Component nie woła API po stronie
# serwera (całe pobieranie danych idzie przez TanStack Query w komponentach
# klienckich) — względny URL w `fetch` na serwerze Node nie miałby do czego
# się odnieść. Jeśli kiedyś pojawi się fetch w Server Component, ta wartość
# musi wrócić do absolutnej.
ARG NEXT_PUBLIC_API_URL=/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

COPY . .

# `public/` jest w repo puste, a git nie śledzi pustych katalogów — po
# `git clone` na VPS-ie po prostu go nie ma i `COPY /app/public` w stopniu
# `prod` niżej wywala build. Lokalnie katalog istnieje, więc błąd nie wyszedłby
# przed pierwszym wdrożeniem.
RUN mkdir -p public

RUN npm run build


FROM node:22-slim AS prod

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Nie-root: użytkownik `node` (UID 1000) jest już w obrazie bazowym. Własny
# `useradd --uid 1000` wywalał build kodem 4 („UID already in use") — obraz
# `node` ma to konto od zawsze, w przeciwieństwie do `python:3.12-slim`,
# gdzie 1000 jest wolne (patrz `backend/Dockerfile`).
#
# `output: "standalone"` (frontend/next.config.ts) pakuje serwer razem z
# WYŁĄCZNIE tymi zależnościami, które realnie są importowane — obraz nie
# niesie całego `node_modules` ani źródeł. `static/` i `public/` stoją poza
# tą paczką i trzeba je dołożyć osobno.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public

USER node

EXPOSE 3000

CMD ["node", "server.js"]
