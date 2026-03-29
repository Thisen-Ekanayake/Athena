# Use Node.js for building/running
FROM node:20-alpine

WORKDIR /app

# Install dependencies first (for better caching)
COPY package*.json ./
RUN npm install

# Copy source code
COPY . .

# Expose Vite's default port
EXPOSE 5173

# Start Vite with --host to allow external access
CMD ["npm", "run", "dev", "--", "--host"]
