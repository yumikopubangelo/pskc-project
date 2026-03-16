# Frontend Dockerfile - Development Only
# For production, use Dockerfile.production with nginx
FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Expose Vite dev server port
EXPOSE 3000

# Start Vite dev server
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ============================================================
# PRODUCTION BUILD INSTRUCTIONS:
# ============================================================
# 
# To build for production:
# 
# 1. Build the React app:
#    npm run build
# 
# 2. Or use the production Dockerfile:
#    docker build -f Dockerfile.production -t pskc-frontend:latest .
# 
# 3. The production build will serve static files via nginx
#    and proxy API calls to the backend automatically.
# ============================================================
