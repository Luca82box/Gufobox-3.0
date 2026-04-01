FROM python:3.11-slim

WORKDIR /app

# Variabili d'ambiente per un comportamento prevedibile in container
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Installa le dipendenze Python
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copia il progetto
COPY . .

# Espone la porta del server Flask
EXPOSE 5000

# Health check minimale: verifica che il server risponda sull'endpoint /api/ping
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/ping')" || exit 1

# Avvia il backend
CMD ["python", "main.py"]
