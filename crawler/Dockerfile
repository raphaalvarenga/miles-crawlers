FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget gnupg2 curl unzip fonts-liberation \
    libnss3 libx11-6 libxcomposite1 libxrandr2 libxdamage1 libxfixes3 libxkbcommon0 libgbm1 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libgtk-3-0 libasound2 libpangocairo-1.0-0 libxss1 \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Try to install chromium from apt (sufficient for Camoufox/playwright headless use).
RUN apt-get update && apt-get install -y --no-install-recommends chromium \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY crawler/requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip
RUN pip install -r requirements.txt
RUN camoufox fetch

COPY crawler /app

ENV QUEUE_NAME=crawl.smiles
ENV PREFETCH_COUNT=1
ENV PYTHONPATH=/app/src:/app

CMD ["python", "run_worker.py"]
