FROM python:3.14.6-slim-trixie


COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /bin/

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-install-project --no-dev

COPY . .

RUN mkdir -p /app/logs /app/exports/analysis /app/exports/articles /app/dist && \
    chmod +x /app/docker-build/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["sh", "/app/docker-build/entrypoint.sh"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
