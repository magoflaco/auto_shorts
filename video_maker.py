# -*- coding: utf-8 -*-
"""
video_maker.py
==============
Renderiza un video vertical (9:16) con FFmpeg a partir de:
  - escenas.json  (metadata + timestamps)
  - narracion.mp3 (audio TTS)
  - escena_XX.png (imágenes anime)
  - musica.mp3    (opcional, música de fondo)

Se ejecuta desde la carpeta de la historia (cwd = historias/<nombre>/).
También importable como módulo.
"""

import os
import sys
import subprocess
import json
import glob

import config


# ── Parámetros de video ───────────────────────────────────────────

DEBUG_MODE   = config.VIDEO_DEBUG_MODE
WIDTH_FINAL  = config.VIDEO_WIDTH
HEIGHT_FINAL = config.VIDEO_HEIGHT
FPS_FINAL    = config.VIDEO_FPS
CRF_VALUE    = config.VIDEO_CRF

if DEBUG_MODE:
    print("MODO DEBUG ACTIVADO: resolución y calidad reducidas.")
    WIDTH_FINAL  = 270
    HEIGHT_FINAL = 480
    FPS_FINAL    = 10
    CRF_VALUE    = "35"


# ══════════════════════════════════════════════════════════════════
# Utilidades
# ══════════════════════════════════════════════════════════════════

def get_audio_duration(audio_path: str) -> float:
    """Obtiene la duración de un audio en segundos usando ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        print(f"ERROR: No se pudo obtener la duración de {audio_path}.")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════
# Pipeline principal
# ══════════════════════════════════════════════════════════════════

def crear_video_desde_json(
    ruta_json: str,
    ruta_audio: str,
    nombre_salida: str = "short_final.mp4",
    silencio_ini: float = 1.0,
    silencio_fin: float = 2.0,
    duracion_transicion: float = 1.5,
    usar_musica: bool = True,
):
    """Renderiza el video final con FFmpeg."""

    print(f"--- Iniciando Generador FFmpeg ({'DEBUG' if DEBUG_MODE else 'PRODUCCION'}) ---")

    # 1. Validar archivos
    if not os.path.exists(ruta_audio):
        print(f"ERROR: No se encontró el audio: {ruta_audio}")
        return
    if not os.path.exists(ruta_json):
        print(f"ERROR: No se encontró el JSON: {ruta_json}")
        return

    # 2. Leer JSON y extraer imágenes + timestamps
    try:
        with open(ruta_json, "r", encoding="utf-8") as f:
            datos = json.load(f)

        escenas    = datos.get("escenas", [])
        imagenes   = []
        timestamps = []

        for escena in escenas:
            imagenes.append(escena["image_file"])
            timestamps.append(float(escena.get("timestamp_seconds", 0)))

    except Exception as e:
        print(f"ERROR al leer el JSON: {e}")
        return

    num_imgs = len(imagenes)
    if num_imgs == 0:
        print("ERROR: El JSON no contiene imágenes válidas.")
        return

    for img in imagenes:
        if not os.path.exists(img):
            print(f"ERROR: La imagen '{img}' no existe en la carpeta.")
            return

    # 3. Cálculos de tiempo
    duracion_audio_original = get_audio_duration(ruta_audio)
    duracion_total_video    = silencio_ini + duracion_audio_original + silencio_fin

    print(f"Audio original: {duracion_audio_original:.2f}s")
    print(f"Duración total (con silencios): {duracion_total_video:.2f}s")

    tiempos_visuales_netos = []
    for i in range(num_imgs):
        if i < num_imgs - 1:
            t_neto = timestamps[i + 1] - timestamps[i]
        else:
            t_neto = max(1.0, duracion_audio_original - timestamps[i])

        if i == 0:
            t_neto += silencio_ini
        if i == num_imgs - 1:
            t_neto += silencio_fin

        tiempos_visuales_netos.append(t_neto)

    # 4. Descargar música de fondo (si aplica)
    if usar_musica and not os.path.exists("musica.mp3"):
        print("\n[INFO] Solicitando pista musical de fondo...")
        mp3_antes = set(glob.glob("*.mp3"))
        try:
            subprocess.run(
                [sys.executable, str(config.MUSIC_DOWNLOADER)],
                check=True,
            )
            mp3_despues = set(glob.glob("*.mp3"))
            nuevos_mp3  = mp3_despues - mp3_antes

            if nuevos_mp3:
                archivo_descargado = list(nuevos_mp3)[0]
                if os.path.exists("musica.mp3"):
                    os.remove("musica.mp3")
                os.rename(archivo_descargado, "musica.mp3")
                print(f"[INFO] Música preparada: musica.mp3\n")
            else:
                print("AVISO: No se descargó música nueva.\n")
        except Exception as e:
            print(f"AVISO: Error al obtener música: {e}\n")

    # 5. Construcción del comando FFmpeg
    inputs       = []
    filter_chain = []

    for img in imagenes:
        inputs.extend(["-i", img])

    # Pre-procesamiento y zoom
    for i in range(num_imgs):
        v_in     = f"[{i}:v]"
        v_scaled = f"[v{i}_scaled]"
        v_zoomed = f"[v{i}_zoomed]"

        scale_pad = (
            f"{v_in}scale={WIDTH_FINAL}:{HEIGHT_FINAL}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH_FINAL}:{HEIGHT_FINAL}:(ow-iw)/2:(oh-ih)/2:black{v_scaled}"
        )

        duracion_clip_real = tiempos_visuales_netos[i] + duracion_transicion
        frames_clip = int(duracion_clip_real * FPS_FINAL) + 90

        zoom = (
            f"{v_scaled}zoompan=z='zoom+0.0005':d={frames_clip}:fps={FPS_FINAL}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={WIDTH_FINAL}x{HEIGHT_FINAL},"
            f"setsar=1{v_zoomed}"
        )

        filter_chain.append(scale_pad)
        filter_chain.append(zoom)

    # Transiciones (Xfade)
    if num_imgs > 1:
        current_stream = "[v0_zoomed]"
        offset_time = 0
        for i in range(1, num_imgs):
            next_stream = f"[v{i}_zoomed]"
            offset_time += tiempos_visuales_netos[i - 1]

            new_name = f"[v{i}_xfaded]" if i < num_imgs - 1 else "[video_ensamblado]"

            xfade = (
                f"{current_stream}{next_stream}xfade=transition=fade:"
                f"duration={duracion_transicion}:offset={offset_time}{new_name}"
            )
            filter_chain.append(xfade)
            current_stream = new_name
    else:
        filter_chain.append("[v0_zoomed]null[video_ensamblado]")

    # Fade in/out
    start_fade_out = duracion_total_video - silencio_fin
    fade = (
        f"[video_ensamblado]fade=t=in:st=0:d={silencio_ini},"
        f"fade=t=out:st={start_fade_out}:d={silencio_fin},"
        f"tpad=stop_mode=clone:stop_duration=3[video_final]"
    )
    filter_chain.append(fade)

    # Audio
    audio_index = num_imgs
    inputs.extend(["-i", ruta_audio])
    delay_ms = int(silencio_ini * 1000)

    if usar_musica and os.path.exists("musica.mp3"):
        inputs.extend(["-stream_loop", "-1", "-i", "musica.mp3"])

        narracion = f"[{audio_index}:a]adelay={delay_ms}|{delay_ms},apad[narracion_lista]"
        musica    = f"[{audio_index + 1}:a]volume=0.1,afade=t=out:st={start_fade_out}:d={silencio_fin}[musica_lista]"
        mix       = "[narracion_lista][musica_lista]amix=inputs=2:duration=first:dropout_transition=2[audio_final]"

        filter_chain.append(narracion)
        filter_chain.append(musica)
        filter_chain.append(mix)
    else:
        audio_filter = f"[{audio_index}:a]adelay={delay_ms}|{delay_ms},apad[audio_final]"
        filter_chain.append(audio_filter)

    # Ensamblar comando
    full_filter = ";".join(filter_chain)

    ffmpeg_cmd = ["ffmpeg", "-y"]
    ffmpeg_cmd.extend(inputs)
    ffmpeg_cmd.extend([
        "-filter_complex", full_filter,
        "-map", "[video_final]",
        "-map", "[audio_final]",
        "-t", str(duracion_total_video),
        "-c:v", "libx264",
        "-preset", "ultrafast" if DEBUG_MODE else "fast",
        "-crf", CRF_VALUE,
        "-c:a", "aac", "-b:a", "192k",
        "-r", str(FPS_FINAL),
        "-pix_fmt", "yuv420p",
        nombre_salida,
    ])

    print("\nIniciando renderizado con FFmpeg...")

    try:
        output_cfg = subprocess.DEVNULL if not DEBUG_MODE else None
        subprocess.run(ffmpeg_cmd, check=True, stdout=output_cfg, stderr=output_cfg)
        print(f"\nOK: Video generado: {nombre_salida}")
    except subprocess.CalledProcessError:
        print("\nERROR al ejecutar FFmpeg. Activa DEBUG_MODE para ver detalles.")


# ══════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    crear_video_desde_json(
        ruta_json="escenas.json",
        ruta_audio="narracion.mp3",
        nombre_salida="video.mp4",
        silencio_ini=1.0,
        silencio_fin=2.0,
        duracion_transicion=1.5,
        usar_musica=True,
    )