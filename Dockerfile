# Usiamo un'immagine Python snella e moderna
FROM python:3.12-slim

# Impostazioni per non generare file .pyc e vedere i log subito
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /code

# Installiamo le dipendenze di sistema necessarie per PostgreSQL
RUN apt-get update && apt-get install -y libpq-dev gcc gettext && rm -rf /var/lib/apt/lists/*

# Installazione Chromium e Driver (Più stabile su Docker e compatibile ARM/Mac M1)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Installiamo le librerie Python
COPY requirements.txt /code/
RUN pip install --no-cache-dir -r requirements.txt

# Copiamo il resto del codice
COPY . /code/
