FROM python:3.11-slim

# Cache-bust: 2026-08-17 force rebuild
WORKDIR /app

# Install system deps including git
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose the port Render expects
ENV PORT=8000
EXPOSE 8000

CMD ["python", "server.py"]
