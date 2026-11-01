# Container startup candidate only. APP_ENV=container_smoke keeps the local
# same-host Runner and preview disabled until production adapters are ready.
FROM node:22-bookworm-slim AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.11-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=container_smoke \
    MYATOM_DATA_DIR=/tmp/myatom-data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system myatom \
    && useradd --system --gid myatom --home-dir /app myatom
COPY --chown=myatom:myatom backend/ ./backend/
COPY --chown=myatom:myatom templates/react-vite/ ./templates/react-vite/
COPY --chown=myatom:myatom examples/ ./examples/
COPY --from=web-build --chown=myatom:myatom /build/web/dist/ ./web/dist/
USER myatom
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import json, urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3))['ok']"
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
