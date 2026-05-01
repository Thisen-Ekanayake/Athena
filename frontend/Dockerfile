# Stage 1 — build
# Full Node image compiles the React app with Vite.
# All dev dependencies, source maps, and build tooling stay in this stage only.
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2 — serve
# Copies only the compiled dist/ folder into a bare nginx image (~50MB total).
# Nothing from Stage 1 ends up in the final image.
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
