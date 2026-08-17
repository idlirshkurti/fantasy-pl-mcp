FROM python:3.11-slim

WORKDIR /app

# Install system deps if needed (none required for this simple app)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose the port Render expects
ENV PORT=8000
EXPOSE 8000

CMD ["python", "server.py"]
