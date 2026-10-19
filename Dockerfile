# Hosted Lemma. Set LEMMA_ALLOWED_HOSTS to the domain it is reached by, and keep /data on a volume.
FROM ghcr.io/astral-sh/uv:0.11.28-python3.12-trixie-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN uv sync --locked --no-install-project
COPY lemma ./lemma
RUN uv sync --locked

RUN useradd --create-home lemma && mkdir /data && chown lemma /data
USER lemma
ENV LEMMA_HOME=/data LEMMA_HOST=0.0.0.0 PORT=8765
EXPOSE 8765
CMD ["sh", "-c", "exec /app/.venv/bin/lemma --port \"$PORT\" --no-browser"]
