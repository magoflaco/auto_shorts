# -*- coding: utf-8 -*-
"""
music_downloader.py
===================
Descarga una pista de música ambient/terror aleatoria desde Freesound.
Se ejecuta desde la carpeta de la historia (cwd = historias/<nombre>/).
"""

import random
import requests
import config


def descargar_fondo_terror_aleatorio():
    """Busca y descarga un MP3 aleatorio de Freesound (60-120s, dark ambient)."""
    print("[INFO] Iniciando búsqueda de pistas de terror en Freesound...")

    url = "https://freesound.org/apiv2/search/text/"

    params = {
        "query": "dark ambient drone creepy",
        "filter": "duration:[60.0 TO 120.0]",
        "fields": "id,name,previews",
        "page_size": 30,
    }

    headers = {
        "Authorization": f"Token {config.FREESOUND_API_KEY}",
    }

    try:
        print("[INFO] Conectando con la API...")
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        resultados = data.get("results", [])

        if not resultados:
            print("[ALERTA] No se encontraron audios con esos criterios.")
            return

        audio_elegido = random.choice(resultados)

        nombre_limpio = "".join(
            c for c in audio_elegido["name"]
            if c.isalpha() or c.isdigit() or c == " "
        ).rstrip()
        nombre_archivo = f"{nombre_limpio}_{audio_elegido['id']}.mp3"
        link_descarga = audio_elegido["previews"]["preview-hq-mp3"]

        print(f"[INFO] Pista seleccionada: {nombre_archivo}")
        print(f"[INFO] Descargando desde: {link_descarga}")

        mp3_response = requests.get(link_descarga)
        mp3_response.raise_for_status()

        with open(nombre_archivo, "wb") as f:
            f.write(mp3_response.content)

        print(f"[OK] Descarga completada: '{nombre_archivo}'")

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Problema de conexión o API: {e}")
    except KeyError as e:
        print(f"[ERROR] Formato de respuesta inesperado. Falta clave: {e}")


if __name__ == "__main__":
    descargar_fondo_terror_aleatorio()