FROM node:20

WORKDIR /app

# Install dependencies first (uses package-lock if present)
COPY package.json package-lock.json* ./
# use npm install to avoid lockfile mismatch during iterative development builds
RUN npm install --no-audit --no-fund

# Copy app sources
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
