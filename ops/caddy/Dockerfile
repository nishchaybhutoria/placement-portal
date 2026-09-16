FROM node:26-alpine AS frontend

RUN npm install --global pnpm@11.22.0
WORKDIR /workspace/frontend

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
ARG VITE_BASE_PATH=/portal/
ENV VITE_BASE_PATH=${VITE_BASE_PATH}
RUN pnpm build

FROM caddy:2.11.4-alpine

COPY Caddyfile /etc/caddy/Caddyfile
COPY common/ /srv/common/
COPY --from=frontend /workspace/frontend/dist /srv/portal
