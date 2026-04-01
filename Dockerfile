FROM python:3.11-slim

WORKDIR /app

# Installa le dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il progetto
COPY . .

# Espone la porta del server Flask
EXPOSE 5000

# Avvia il backend
CMD ["python", "main.py"]
