FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system crawler \
    && useradd --system --create-home --gid crawler --shell /usr/sbin/nologin crawler

COPY --chown=crawler:crawler . ./
RUN mkdir -p /app/data /app/debug \
    && chown -R crawler:crawler /app

USER crawler

ENTRYPOINT ["python", "main.py"]
