# Stage 1: Compile C PoW Worker
FROM gcc:12 AS builder
WORKDIR /app
COPY pow_worker.c .
RUN apt-get update && apt-get install -y libssl-dev && \
    gcc -O3 -o pow_worker pow_worker.c -lssl -lcrypto

# Stage 2: Runtime with Python + Node.js
FROM python:3.11-slim
WORKDIR /app

# Install Node.js
RUN apt-get update && \
    apt-get install -y nodejs npm libssl3 && \
    rm -rf /var/lib/apt/lists/*

# Copy compiled PoW worker from builder
COPY --from=builder /app/pow_worker .
RUN chmod +x pow_worker

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Node.js dependencies
COPY package.json .
RUN npm install --production

# Copy application files
COPY mine_web.py .
COPY sign.js .
COPY pow_worker.js .

# Runtime configuration
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ping || exit 1

CMD ["python", "mine_web.py"]
