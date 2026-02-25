# Auto Shorts v2

Generador automático de YouTube Shorts de terror psicológico con imágenes anime.

## Pipeline

1. **Generación de historia** → Groq LLaMA (prompt creativo + historia completa)
2. **Narración TTS** → Deepgram (voz en español)
3. **Imágenes anime** → Pollinations.ai (5 escenas en estilo anime 9:16)
4. **Música de fondo** → Freesound (ambient/dark drone)
5. **Renderizado de video** → FFmpeg (zoom, transiciones, fade, mezcla de audio)
6. **Subida a YouTube** → YouTube Data API v3 (OAuth2)
7. **Loop automático** → Cada 3h genera y sube un nuevo short

## Setup en Ubuntu (Oracle Cloud)

### 1. Clonar e instalar

```bash
cd /home/ubuntu
git clone <tu-repo> auto_shorts
cd auto_shorts

# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Instalar ffmpeg
sudo apt update && sudo apt install -y ffmpeg
```

### 2. Configurar credenciales

```bash
# Copiar template y rellenar API keys
cp .env.example .env
nano .env

# Copiar credenciales de YouTube desde tu máquina local
scp client_secrets.json ubuntu@<IP>:/home/ubuntu/auto_shorts/
scp token.json ubuntu@<IP>:/home/ubuntu/auto_shorts/
```

### 3. Ejecutar (opción A: systemd)

```bash
sudo cp auto_shorts.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable auto_shorts
sudo systemctl start auto_shorts

# Ver logs
journalctl -u auto_shorts -f
```

### 3. Ejecutar (opción B: screen/tmux)

```bash
source venv/bin/activate
python -u automatizador.py
```

### 3. Ejecutar (opción C: Docker)

```bash
docker build -t auto_shorts .
docker run -d --name auto_shorts \
  -v $(pwd)/.env:/app/.env \
  -v $(pwd)/client_secrets.json:/app/client_secrets.json \
  -v $(pwd)/token.json:/app/token.json \
  -v $(pwd)/historias:/app/historias \
  auto_shorts
```

## Estructura

```
auto_shorts/
├── config.py                  # Configuración central (.env)
├── automatizador.py           # Loop principal (cada 3h)
├── horror_story_generator.py  # Pipeline de generación
├── video_maker.py             # Renderizado FFmpeg
├── video_uploader.py          # Subida a YouTube
├── music_downloader.py        # Descarga de Freesound
├── anime_gen.py               # Generación de imágenes
├── .env                       # API keys (NO subir a Git)
├── .env.example               # Template de .env
├── client_secrets.json        # YouTube OAuth (NO subir a Git)
├── token.json                 # YouTube token (NO subir a Git)
├── requirements.txt           # Dependencias Python
├── Dockerfile                 # Para deploy con Docker
├── auto_shorts.service        # Para deploy con systemd
├── .gitignore
└── historias/                 # Carpetas generadas (una por historia)
```

## APIs necesarias

| Servicio | Variable en .env | Para qué |
|---|---|---|
| Groq | `GROQ_AUDIO_API_KEY` | Generación de título/descripción |
| Groq | `GROQ_RESPONSE_API_KEY` | Historia y prompts de imagen |
| Deepgram | `DEEPGRAM_API_KEY` | Text-to-Speech |
| Pollinations | `POLLINATIONS_API_KEY` | Imágenes anime |
| Freesound | `FREESOUND_API_KEY` | Música de fondo |
| Discord | `DISCORD_WEBHOOK_URL` | Notificaciones |
| YouTube | `client_secrets.json` | Upload de videos |
