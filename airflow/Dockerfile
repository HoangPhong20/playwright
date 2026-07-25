FROM apache/airflow:3.3.0-python3.12

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/airflow/app

COPY requirements.txt /tmp/crawler-requirements.txt

USER airflow

RUN pip install --no-cache-dir -r /tmp/crawler-requirements.txt

USER root

RUN mkdir -p /opt/airflow/app/data /opt/airflow/app/debug /ms-playwright \
    && PYTHONPATH=/home/airflow/.local/lib/python3.12/site-packages playwright install-deps chromium \
    && chown -R airflow:root /opt/airflow/app /ms-playwright \
    && rm -rf /var/lib/apt/lists/* /tmp/crawler-requirements.txt

USER airflow

RUN playwright install chromium

COPY --chown=airflow:root . /opt/airflow/app

WORKDIR /opt/airflow/app
