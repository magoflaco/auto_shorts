# -*- coding: utf-8 -*-
"""
config.py
=========
Módulo central de configuración.
Carga variables de entorno desde .env y expone constantes para todo el proyecto.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Rutas base ────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent.resolve()
HISTORIAS_DIR = BASE_DIR / "historias"

# ── Cargar .env ───────────────────────────────────────────────────
load_dotenv(BASE_DIR / ".env")

# ── API Keys ──────────────────────────────────────────────────────
GROQ_AUDIO_API_KEY    = os.getenv("GROQ_AUDIO_API_KEY", "")
GROQ_RESPONSE_API_KEY = os.getenv("GROQ_RESPONSE_API_KEY", "")
DEEPGRAM_API_KEY      = os.getenv("DEEPGRAM_API_KEY", "")
POLLINATIONS_API_KEY  = os.getenv("POLLINATIONS_API_KEY", "")
FREESOUND_API_KEY     = os.getenv("FREESOUND_API_KEY", "")

# ── Discord ───────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ── Automatizador ─────────────────────────────────────────────────
INTERVALO_HORAS = int(os.getenv("INTERVALO_HORAS", "3"))
MARKER_FILE     = "subido.txt"
STATE_FILE      = BASE_DIR / "estado.json"

# ── Rutas de scripts ──────────────────────────────────────────────
GENERATOR_SCRIPT = BASE_DIR / "horror_story_generator.py"
UPLOADER_SCRIPT  = BASE_DIR / "video_uploader.py"
VIDEO_MAKER      = BASE_DIR / "video_maker.py"
MUSIC_DOWNLOADER = BASE_DIR / "music_downloader.py"

# ── YouTube OAuth ─────────────────────────────────────────────────
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
TOKEN_FILE          = BASE_DIR / "token.json"

# ── Parámetros de imagen (Pollinations) ───────────────────────────
IMAGE_MODEL  = "zimage"
IMAGE_WIDTH  = 768
IMAGE_HEIGHT = 1365   # 9:16 vertical

ANIME_SUFFIX = (
    ", anime style, high quality, vibrant colors, detailed illustration, "
    "horror aesthetic, dark atmosphere, cel shading, sharp lineart, cinematic lighting, "
    "Studio Ghibli meets horror"
)

# ── Parámetros de video (FFmpeg) ──────────────────────────────────
VIDEO_WIDTH      = 720#1080
VIDEO_HEIGHT     = 1280#1920
VIDEO_FPS        = 24#30
VIDEO_CRF        = "23"
VIDEO_DEBUG_MODE = False

# ── Modelos Groq ──────────────────────────────────────────────────
VOICE_MODEL = "aura-2-celeste-es"
MODEL_SMALL = "llama-3.1-8b-instant"
MODEL_BIG   = "llama-3.3-70b-versatile"

# IG
IG_USERNAME = os.getenv("IG_USERNAME", "")
IG_PASSWORD = os.getenv("IG_PASSWORD", "")
# Ruta para las cookies de sesión de TikTok
TIKTOK_COOKIES = BASE_DIR / "tiktok_cookies.json"
TIKTOK_SESSIONID = os.getenv("TIKTOK_SESSIONID", "")