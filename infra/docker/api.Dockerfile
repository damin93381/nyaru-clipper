FROM python:3.11-slim

ARG TARGETARCH=amd64

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.bin:${PATH}" \
    BBDOWN_VERSION=1.6.3 \
    BBDOWN_BUILD_DATE=20240814

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.5.29 /uv /uvx /bin/

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir yt-dlp

RUN mkdir -p /app/.bin /opt/bbdown \
    && case "${TARGETARCH}" in \
        amd64) bbdown_arch="x64" ;; \
        arm64) bbdown_arch="arm64" ;; \
        *) printf 'unsupported TARGETARCH for BBDown: %s\n' "${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/nilaoda/BBDown/releases/download/${BBDOWN_VERSION}/BBDown_${BBDOWN_VERSION}_${BBDOWN_BUILD_DATE}_linux-${bbdown_arch}.zip" -o /tmp/bbdown.zip \
    && python -c "import zipfile; zipfile.ZipFile('/tmp/bbdown.zip').extractall('/opt/bbdown')" \
    && chmod +x /opt/bbdown/BBDown \
    && ln -sf /opt/bbdown/BBDown /app/.bin/BBDown \
    && ln -sf /usr/local/bin/yt-dlp /app/.bin/yt-dlp \
    && ln -sf /usr/bin/ffmpeg /app/.bin/ffmpeg \
    && ln -sf /usr/bin/ffprobe /app/.bin/ffprobe \
    && rm -f /tmp/bbdown.zip

RUN useradd --create-home --shell /bin/bash appuser

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/README.md ./README.md
COPY backend/.python-version ./.python-version
COPY backend/app ./app

RUN uv sync --no-dev

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
