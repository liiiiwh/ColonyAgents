# syntax=docker/dockerfile:1.7
# Next.js standalone 构建（next.config.js 已设 output:'standalone'）。监听 3022 与 dev 一致。
FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# Next evaluates rewrites() at BUILD time for `output: standalone` and bakes the /api
# proxy destination into the manifest — a runtime BACKEND_URL env is ignored. So the
# backend service URL must be present as a build arg here. Compose passes http://backend:9022.
ARG BACKEND_URL=http://backend:9022
ENV BACKEND_URL=${BACKEND_URL}
RUN npm run build

FROM node:20-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3022 \
    HOSTNAME=0.0.0.0
# standalone server + 静态资源
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3022
CMD ["node", "server.js"]
