# ============================================================
# Stage 1: Frontend builder — compila il frontend Vue
# ============================================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

# Installa le dipendenze npm (layer cacheable)
COPY frontend/package*.json ./
RUN npm install

# Copia i sorgenti del frontend e compila
COPY frontend/ ./
RUN npm run build

# ============================================================
# Stage 2: Backend — server Python + frontend buildato
# ============================================================
FROM python:3.11-slim

WORKDIR /app

# Variabili d'ambiente per un comportamento prevedibile in container
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Installa le dipendenze Python
COPY requirements.txt requirements-hw.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-hw.txt || true

# Copia il backend
COPY . .

# Copia il frontend buildato dallo stage 1 nella posizione corretta
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Espone la porta del server Flask (serve sia le API che il frontend)
EXPOSE 5000

# Health check minimale: verifica che il server risponda sull'endpoint /api/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

# Avvia il backend
CMD ["python", "main.py"]

