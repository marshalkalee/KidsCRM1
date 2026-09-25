# nginx со сборкой frontend2 внутри (TRU-79). Контекст сборки — корень
# репозитория (docker-compose: context: ., dockerfile: infra/nginx/Dockerfile).

FROM node:22-alpine AS frontend
WORKDIR /app
# Сначала только манифесты — слой с node_modules кэшируется, пока не меняются зависимости.
COPY frontend2/package.json frontend2/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend2/ ./
RUN npm run build

FROM nginx:1.27-alpine
# Дев — nginx.conf, staging — nginx.staging.conf (build arg в docker-compose.staging.yml).
ARG NGINX_CONF=nginx.conf
COPY infra/nginx/${NGINX_CONF} /etc/nginx/nginx.conf
COPY infra/nginx/app.conf /etc/nginx/app.conf
COPY --from=frontend /app/dist /usr/share/nginx/html
