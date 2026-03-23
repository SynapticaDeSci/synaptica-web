# Synaptica Frontend — Next.js
FROM node:20-slim AS builder
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ .

ARG NEXT_PUBLIC_BACKEND_URL=https://synaptica-api-812950212515.us-central1.run.app
ARG NEXT_PUBLIC_RESEARCH_URL=https://synaptica-research-812950212515.us-central1.run.app
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_RESEARCH_URL=$NEXT_PUBLIC_RESEARCH_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 8080
ENV PORT=8080

CMD ["node", "server.js"]
