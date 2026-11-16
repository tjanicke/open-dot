FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ohioselections.py .

# Data is mounted read-only at /app/data (see docker-compose service block)
ENV ODOT_DATA_DIR=/app/data
EXPOSE 8765

CMD ["solara", "run", "ohioselections.py", "--host=0.0.0.0", "--port=8765"]
