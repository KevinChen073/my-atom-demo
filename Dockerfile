# Defaults to health-only smoke mode. APP_ENV=azure_demo enables a trusted
# single-container demo; /app/data is a temporary build workspace.
FROM node:22-bookworm-slim AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
COPY examples/ ../examples/
COPY design/v3/icons/ ../design/v3/icons/
RUN npm run build

FROM python:3.11-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=container_smoke \
    MYATOM_DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt requirements-azure.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends libltdl7 libkrb5-3 libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements-azure.txt \
    && groupadd --system myatom \
    && useradd --system --gid myatom --home-dir /app myatom \
    && mkdir /app/data \
    && chown myatom:myatom /app/data
COPY --from=web-build /usr/local/bin/node /usr/local/bin/node
COPY --from=web-build /usr/local/lib/node_modules/npm/ /usr/local/lib/node_modules/npm/
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && node --version && npm --version
COPY --chown=myatom:myatom backend/ ./backend/
COPY --chown=myatom:myatom templates/react-vite/ ./templates/react-vite/
COPY --chown=myatom:myatom examples/ ./examples/
COPY --from=web-build --chown=myatom:myatom /build/web/dist/ ./web/dist/
USER myatom
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import json, urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3))['ok']"
CMD ["uvicorn", "backend.container_entry:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
