# -*- coding: utf-8 -*-
"""
video_uploader.py
=================
Genera título/descripción con Groq y sube un video a YouTube, Instagram y TikTok.

Cada función de subida retorna un dict:
  {"ok": bool, "link": str|None, "error": str|None}
"""

import os
import sys
import json
import time
import traceback
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from groq import Groq
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import googleapiclient.discovery
from googleapiclient.http import MediaFileUpload

# Nuevas librerías
from instagrapi import Client as IgClient
from tiktok_uploader.upload import upload_video

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
        "Eres un experto en redes sociales. Lee la siguiente historia y genera un "
        "título llamativo (máximo 60 caracteres) y una descripción atractiva que incluya "
        "hashtags #shorts #reels #terror y otros relacionados con la historia. Responde ÚNICAMENTE "
        "con un objeto JSON válido con las claves 'titulo' y 'descripcion'."
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
# 2. YouTube
# ══════════════════════════════════════════════════════════════════

def obtener_servicio_youtube():
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None
    token_path = str(config.TOKEN_FILE)
    secrets_path = str(config.CLIENT_SECRETS_FILE)

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, scopes)
            if os.environ.get("DISPLAY") or sys.platform == "win32":
                creds = flow.run_local_server(port=0)
            else:
                creds = flow.run_console()
        with open(token_path, "w") as token:
            token.write(creds.to_json())

    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)


def subir_youtube(archivo_video: str, titulo: str, descripcion: str) -> dict:
    """Sube a YouTube. Retorna {"ok": bool, "link": str|None, "error": str|None}."""
    print("\n[YouTube] Iniciando subida...")
    try:
        youtube = obtener_servicio_youtube()
        cuerpo_solicitud = {
            "snippet": {
                "title": titulo,
                "description": descripcion,
                "categoryId": "24",
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

        respuesta = request.execute()
        video_id = respuesta["id"]
        link = f"https://youtu.be/{video_id}"
        print(f"[YouTube] Video subido OK: {link}")
        return {"ok": True, "link": link, "error": None}
    except Exception as e:
        error_detail = f"{type(e).__name__}: {e}"
        print(f"[YouTube] ERROR: {error_detail}")
        return {"ok": False, "link": None, "error": error_detail}


# ══════════════════════════════════════════════════════════════════
# 3. Instagram Reels
# ══════════════════════════════════════════════════════════════════

def subir_instagram(archivo_video: str, titulo: str, descripcion: str) -> dict:
    """Sube a Instagram. Retorna {"ok": bool, "link": str|None, "error": str|None}."""
    print("\n[Instagram] Iniciando subida...")
    if not config.IG_USERNAME or not config.IG_PASSWORD:
        return {"ok": False, "link": None, "error": "Faltan credenciales IG_USERNAME/IG_PASSWORD en .env"}

    try:
        cl = IgClient()
        cl.login(config.IG_USERNAME, config.IG_PASSWORD)

        caption = f"{titulo}\n\n{descripcion}"
        media = cl.clip_upload(
            archivo_video,
            caption,
            extra_data={"share_to_feed": 1}
        )
        link = f"https://www.instagram.com/reel/{media.code}/"
        print(f"[Instagram] Video subido OK: {link}")
        return {"ok": True, "link": link, "error": None}
    except Exception as e:
        error_detail = f"{type(e).__name__}: {e}"
        print(f"[Instagram] ERROR: {error_detail}")
        return {"ok": False, "link": None, "error": error_detail}


# ══════════════════════════════════════════════════════════════════
# 4. TikTok
# ══════════════════════════════════════════════════════════════════

def subir_tiktok(archivo_video: str, titulo: str, descripcion: str) -> dict:
    """Sube a TikTok usando el archivo completo tiktok_cookies.txt."""
    print("\n[TikTok] Iniciando subida...")
    
    # Apuntamos directamente a tu archivo de cookies real
    cookie_file = "tiktok_cookies.txt"

    if not os.path.exists(cookie_file):
        error_msg = f"No se encontró el archivo de cookies: {cookie_file}"
        print(f"[TikTok] ERROR: {error_msg}")
        return {"ok": False, "link": None, "error": error_msg}

    try:
        # Pasamos el archivo de cookies directamente. 
        # Separamos el título de la descripción con un salto de línea (\n)
        failed = upload_video(
            archivo_video,
            description=f"{titulo}\n{descripcion}",
            cookies=cookie_file,
            headless=False # Mantenemos en False para que funcione con xvfb-run
        )

        if failed:
            error_detail = f"upload_video retornó error: {failed}"
            print(f"[TikTok] ERROR: {error_detail}")
            return {"ok": False, "link": None, "error": error_detail}

        print("[TikTok] Video subido OK.")
        return {"ok": True, "link": "(subido, link no disponible)", "error": None}

    except Exception as e:
        error_detail = f"{type(e).__name__}: {e}"
        print(f"[TikTok] ERROR FATAL: {error_detail}")
        return {"ok": False, "link": None, "error": error_detail}


# ══════════════════════════════════════════════════════════════════
# 5. Pipeline principal
# ══════════════════════════════════════════════════════════════════

def subir(json_path: str, video_path: str) -> dict:
    """
    Pipeline completo multiplataforma.
    Retorna dict con resultados por plataforma.
    """
    print("1. Consultando a Groq para generar metadatos...")
    metadatos = generar_metadatos_groq(json_path)
    titulo = metadatos.get("titulo", "Historia de Terror")
    descripcion = metadatos.get("descripcion", "Una historia escalofriante. #Shorts #Reels #terror")

    print(f"   -> Título: {titulo}")
    print(f"   -> Descripción: {descripcion[:50]}...\n")

    print("2. Distribuyendo contenido a las plataformas...")

    resultados = {
        "metadatos": {"titulo": titulo, "descripcion": descripcion},
        "youtube":   subir_youtube(video_path, titulo, descripcion),
        "instagram": subir_instagram(video_path, titulo, descripcion),
        "tiktok":    subir_tiktok(video_path, titulo, descripcion),
    }

    alguno_ok = any(resultados[p]["ok"] for p in ["youtube", "instagram", "tiktok"])
    resultados["alguno_ok"] = alguno_ok
    return resultados


# ══════════════════════════════════════════════════════════════════
# 6. Entry point
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        archivo_json = sys.argv[1]
        archivo_video = sys.argv[2]
    else:
        archivo_json = "escenas.json"
        archivo_video = "video.mp4"

    try:
        resultados = subir(archivo_json, archivo_video)
        print("\n--- Resumen ---")
        for p in ["youtube", "instagram", "tiktok"]:
            r = resultados[p]
            estado = "OK" if r["ok"] else "FALLO"
            print(f"  {p:12s}: {estado}  {r.get('link') or r.get('error') or ''}")
        if not resultados["alguno_ok"]:
            sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)