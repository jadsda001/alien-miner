FROM python:3.11-slim

WORKDIR /app

# Install build tools, Node.js and OpenSSL for C compilation
RUN apt-get update && apt-get install -y \
    gcc \
    libssl-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Node.js dependencies
COPY package.json ./
RUN npm install

# Copy and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source files
COPY . .

# Compile C pow_worker for Linux (high performance + optimized)
RUN gcc -O3 -o pow_worker pow_worker.c -lcrypto

# Hugging Face Spaces uses port 7860
EXPOSE 7860

# Run the mining bot
CMD ["python", "mine_web.py"]
