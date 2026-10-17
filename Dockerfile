FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY salesbot ./salesbot
RUN pip install --no-cache-dir .

RUN useradd --create-home salesbot && mkdir -p /data && chown salesbot /data
USER salesbot
ENV SALESBOT_DATA_DIR=/data
VOLUME ["/data"]

CMD ["python", "-m", "salesbot", "telegram"]
