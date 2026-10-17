FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY salesbot ./salesbot
RUN pip install --no-cache-dir .

RUN useradd --create-home salesbot && mkdir -p /data && chown salesbot /data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV SALESBOT_DATA_DIR=/data SALESBOT_WEB_HOST=0.0.0.0
VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
# Web app by default; use `python -m salesbot telegram` for the Telegram bot.
CMD ["python", "-m", "salesbot", "web"]
