FROM python:3.11-slim

# Instalar ffmpeg y dependencias del sistema
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar proyecto
COPY config.py .
COPY automatizador.py .
COPY horror_story_generator.py .
COPY video_maker.py .
COPY video_uploader.py .
COPY music_downloader.py .
COPY anime_gen.py .

# Estos archivos se montan como volumen o se copian manualmente:
#   .env                 (API keys)
#   client_secrets.json  (YouTube OAuth)
#   token.json           (YouTube token)

# Crear directorio de historias
RUN mkdir -p historias

CMD ["python", "-u", "automatizador.py"]
