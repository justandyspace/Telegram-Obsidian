FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY src /app/src

RUN mkdir -p /data/vault /srv/obsidian-bot/state /srv/obsidian-bot/cache /srv/obsidian-bot/index && \
    chown -R app:app /app /data /srv/obsidian-bot

USER app

CMD ["python", "-m", "src.main", "--role", "bot"]
