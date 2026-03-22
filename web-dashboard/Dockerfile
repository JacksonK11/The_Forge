# ── Build stage ──────────────────────────────────────────────────────────────
FROM node:22-alpine AS build

# Build-time env vars for Vite (baked into bundle at build time)
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_API_SECRET_KEY=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_API_SECRET_KEY=$VITE_API_SECRET_KEY

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

# ── Production stage ─────────────────────────────────────────────────────────
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

# nginx config for SPA routing (all routes return index.html)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
