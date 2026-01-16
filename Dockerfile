# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Installation minimale des dépendances système
RUN apt-get update && apt-get install -y \
    wget \
    xfonts-base \
    xfonts-75dpi \
    && rm -rf /var/lib/apt/lists/*

# Installer wkhtmltopdf
RUN wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.bullseye_amd64.deb \
    && dpkg -i wkhtmltox_0.12.6.1-2.bullseye_amd64.deb \
    || apt-get install -fy

# Copier et installer requirements
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copier l'application
COPY . .

# Télécharger les données NLTK
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords')"

CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app"]