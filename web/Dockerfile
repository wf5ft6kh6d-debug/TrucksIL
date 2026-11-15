# Build context: repository root (needs data/vehicle-profile.schema.json and api/src/polyline.mjs).
FROM node:22.23.5-alpine AS build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci && npm cache clean --force
COPY data/vehicle-profile.schema.json /app/data/
COPY api/src/polyline.mjs /app/api/src/
COPY web/ ./
RUN npm run build

FROM nginx:1.27.5-alpine
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/web/dist /usr/share/nginx/html
EXPOSE 80
