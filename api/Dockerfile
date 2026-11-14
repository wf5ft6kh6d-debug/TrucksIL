# Build context: repository root (see docker-compose.yml).
FROM node:22.23.5-alpine
WORKDIR /app
ENV NODE_ENV=production TRUCKSIL_SCHEMA_DIR=/app/data
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY data/vehicle-profile.schema.json data/restrictions.schema.json ./data/
COPY api/src ./api/src
USER node
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:8080/health >/dev/null || exit 1
CMD ["node", "api/src/server.js"]
