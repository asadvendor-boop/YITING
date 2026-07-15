FROM node:20-bookworm-slim

WORKDIR /app

ARG NEXT_PUBLIC_GATEWAY_URL=""
ARG NEXT_PUBLIC_YITING_MODE="judge"

ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_GATEWAY_URL="${NEXT_PUBLIC_GATEWAY_URL}" \
    NEXT_PUBLIC_YITING_MODE="${NEXT_PUBLIC_YITING_MODE}"

COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci

COPY dashboard/ ./
COPY artifacts/track3-live-paired/summary.json ./public/benchmark/track3-live-paired-summary.json
COPY artifacts/track3-live-paired-postfix/summary.json ./public/benchmark/track3-live-paired-postfix-summary.json
RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]
