# -*- coding: utf-8 -*-
"""
video_uploader.py
=================
Genera título/descripción con Groq y sube un video a YouTube.

Puede usarse como módulo:
    from video_uploader import subir(json_path, video_path)

O como script independiente:
    python video_uploader.py            (usa escenas.json / video.mp4 del cwd)
    python video_uploader.py ruta.json ruta.mp4
"""

import os
import sys
import json

from groq import Groq
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import googleapiclient.discovery
from googleapiclient.http import MediaFileUpload

import config


# ══════════════════════════════════════════════════════════════════
# 1. Metadatos con Groq
# ══════════════════════════════════════════════════════════════════

def generar_metadatos_groq(ruta_json: str) -> dict:
    """Extrae la historia del JSON y genera título/descripción con Groq."""
    with open(ruta_json, "r", encoding="utf-8") as f:
        datos = json.load(f)
        historia = datos.get("historia", "")

    cliente = Groq(api_key=config.GROQ_AUDIO_API_KEY)

    instrucciones = (
        "Eres un experto en YouTube Shorts. Lee la siguiente historia y genera un "
        "título llamativo (máximo 60 caracteres) y una descripción atractiva que incluya "
        "obligatoriamente los hashtags #Shorts y #terror. Responde ÚNICAMENTE con un objeto JSON válido "
        "con las claves 'titulo' y 'descripcion'."
    )

    respuesta = cliente.chat.completions.create(
        model=config.MODEL_SMALL,
        messages=[
            {"role": "system", "content": instrucciones},
            {"role": "user", "content": historia},
        ],
        response_format={"type": "json_object"},
    )

    return json.loads(respuesta.choices[0].message.content)


# ══════════════════════════════════════════════════════════════════
# 2. YouTube OAuth
# ══════════════════════════════════════════════════════════════════

def obtener_servicio_youtube():
    """
    Autentica con YouTube.
    - Si existe token.json válido, lo reutiliza.
    - En servidor headless intenta run_console; si hay display, usa run_local_server.
    """
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None

    token_path   = str(config.TOKEN_FILE)
    secrets_path = str(config.CLIENT_SECRETS_FILE)

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, scopes)
            # En servidor headless (sin DISPLAY), usar consola
            if os.environ.get("DISPLAY") or sys.platform == "win32":
                creds = flow.run_local_server(port=0)
            else:
                creds = flow.run_console()

        with open(token_path, "w") as token:
            token.write(creds.to_json())

    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)


# ══════════════════════════════════════════════════════════════════
# 3. Subida
# ══════════════════════════════════════════════════════════════════

def subir_short_youtube(youtube, archivo_video: str, titulo: str, descripcion: str):
    """Sube un video a YouTube como Short público."""
    cuerpo_solicitud = {
        "snippet": {
            "title": titulo,
            "description": descripcion,
            "categoryId": "24",  # Entretenimiento
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media_file = MediaFileUpload(archivo_video, chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=cuerpo_solicitud,
        media_body=media_file,
    )

    print("Subiendo video... esto puede tomar un par de minutos.")
    respuesta = request.execute()
    video_id = respuesta["id"]
    print(f"Video subido OK. ID: {video_id}")
    print(f"Link: https://youtu.be/{video_id}")
    return video_id


# ══════════════════════════════════════════════════════════════════
# 4. Función principal (usable como módulo)
# ══════════════════════════════════════════════════════════════════

def subir(json_path: str, video_path: str):
    """Pipeline completo: generar metadatos + autenticar + subir."""
    print("1. Consultando a Groq para generar título y descripción...")
    metadatos = generar_metadatos_groq(json_path)
    titulo = metadatos.get("titulo", "Historia de Terror #Shorts")
    descripcion = metadatos.get("descripcion", "Una historia escalofriante. #Shorts #terror")

    print(f"   -> Título: {titulo}")
    print(f"   -> Descripción: {descripcion[:50]}...\n")

    print("2. Autenticando con YouTube...")
    youtube_service = obtener_servicio_youtube()

    print("3. Iniciando subida a YouTube...")
    return subir_short_youtube(youtube_service, video_path, titulo, descripcion)


# ══════════════════════════════════════════════════════════════════
# 5. Entry point
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        archivo_json = sys.argv[1]
        archivo_video = sys.argv[2]
    else:
        archivo_json = "escenas.json"
        archivo_video = "video.mp4"

    try:
        subir(archivo_json, archivo_video)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)