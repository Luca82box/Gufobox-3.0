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

# Avvia il backend
CMD ["python", "main.py"]
