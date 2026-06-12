FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

ENV AGODA_HEADLESS=true \
    AGODA_OUTPUT_DIR=data/raw \
    AGODA_DATE_START=2026-07-01 \
    AGODA_DATE_END=2026-07-01

COPY . .

CMD ["python", "main.py"]
