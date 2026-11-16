FROM python:3.14-slim

WORKDIR /app

# Install system tools needed for some python data packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your source script and data backends into the environment
COPY openselections.py .
COPY ptb_selection_data.parquet .

EXPOSE 8765

# Server-rendered SEO template
COPY templates/ /templates/

CMD ["solara", "run", "openselections.py", "--host=0.0.0.0", "--port=8765"]

# OpenDOT Umami Analytics
COPY assets/ /app/assets/
ENV SOLARA_ASSETS_EXTRA_LOCATIONS=/app/assets
