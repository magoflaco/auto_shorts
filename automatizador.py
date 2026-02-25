# -*- coding: utf-8 -*-
"""
automatizador.py
================
Orquestador continuo del pipeline de YouTube Shorts.

Lógica por ciclo (cada N horas, configurable):
  1. Busca en historias/ carpetas con video.mp4 pero sin subido.txt
     -> Las sube a YouTube y crea subido.txt
  2. Si NO hay pendientes:
     -> Genera nueva historia (horror_story_generator.py)
     -> La sube inmediatamente
  3. Espera N horas y repite.
"""

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta

import config


# ══════════════════════════════════════════════════════════════════
# Utilidades
# ══════════════════════════════════════════════════════════════════

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def discord_notify(titulo: str, descripcion: str, color: int = 0x9B59B6, campos: list = None):
    """Envía un embed a Discord via webhook."""
    if not config.DISCORD_WEBHOOK_URL:
        return

    embed = {
        "title":       titulo,
        "description": descripcion,
        "color":       color,
        "timestamp":   datetime.utcnow().isoformat() + "Z",
        "footer":      {"text": "Automatizador de Shorts"},
        "fields":      campos or [],
    }
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    try:
        req = urllib.request.Request(
            config.DISCORD_WEBHOOK_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Python/auto_shorts",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log("Reporte enviado a Discord OK")
    except Exception as e:
        log(f"AVISO: no se pudo enviar reporte a Discord: {e}")


def run_streaming(script: Path, cwd: Path = None, label: str = "") -> bool:
    """Ejecuta un script Python mostrando su salida en tiempo real."""
    cwd = cwd or config.BASE_DIR
    tag = label or script.name
    log(f">> Ejecutando: {tag}")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout:
            print(f"   {line}", end="", flush=True)
        proc.wait()
        if proc.returncode == 0:
            log(f"<< {tag} finalizó OK")
            return True
        log(f"<< {tag} terminó con error (código {proc.returncode})")
        return False
    except Exception as e:
        log(f"<< ERROR ejecutando {tag}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
# Escaneo de pendientes
# ══════════════════════════════════════════════════════════════════

def get_pendientes() -> list:
    """Carpetas con video.mp4 + escenas.json pero sin subido.txt."""
    if not config.HISTORIAS_DIR.exists():
        return []
    result = []
    for folder in sorted(config.HISTORIAS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        if ((folder / "video.mp4").exists()
                and (folder / "escenas.json").exists()
                and not (folder / config.MARKER_FILE).exists()):
            result.append(folder)
    return result


# ══════════════════════════════════════════════════════════════════
# Subida a YouTube
# ══════════════════════════════════════════════════════════════════

def subir_video(folder: Path) -> bool:
    """
    Sube folder/video.mp4 a YouTube usando video_uploader.subir().
    """
    log(f"Subiendo: {folder.name}")

    json_path  = str((folder / "escenas.json").resolve())
    video_path = str((folder / "video.mp4").resolve())

    output_lines = []
    ok = False
    try:
        # Importar y llamar directamente — sin wrapper ni exec
        from video_uploader import subir
        # Capturar output redirigiendo stdout temporalmente
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            subir(json_path, video_path)
        captured = buf.getvalue()
        for line in captured.splitlines():
            print(f"   {line}", flush=True)
            output_lines.append(line + "\n")
        ok = True
    except Exception as e:
        log(f"ERROR al subir {folder.name}: {e}")
        output_lines.append(f"ERROR: {e}\n")

    if ok:
        # Leer historia para el marker
        try:
            data     = json.loads(Path(json_path).read_text(encoding="utf-8"))
            historia = data.get("historia", "")[:300]
            prompt   = data.get("story_prompt", "")
        except Exception:
            historia = prompt = ""

        marker_content = (
            f"subido: {datetime.now().isoformat()}\n"
            f"carpeta: {folder.name}\n"
            f"video: video.mp4\n"
            f"json: escenas.json\n"
            f"\n--- PROMPT BASE ---\n{prompt}\n"
            f"\n--- HISTORIA (extracto) ---\n{historia}\n"
            f"\n--- OUTPUT DEL UPLOADER ---\n"
            + "".join(output_lines)
        )
        (folder / config.MARKER_FILE).write_text(marker_content, encoding="utf-8")
        log(f"subido.txt creado en {folder.name}/")

        # Extraer link de YouTube del output
        yt_link = ""
        for line in output_lines:
            if "youtu.be/" in line or "youtube.com/watch" in line:
                for token in line.split():
                    if "youtu" in token:
                        yt_link = token.strip()
                        break

        campos_discord = [
            {"name": "Carpeta",  "value": folder.name,          "inline": False},
            {"name": "Prompt",   "value": prompt[:200] or "N/A", "inline": False},
        ]
        if yt_link:
            campos_discord.append({"name": "Link YouTube", "value": yt_link, "inline": False})

        discord_notify(
            titulo      = "Video subido a YouTube",
            descripcion = (historia[:300] + "...") if len(historia) > 300 else historia or "Sin descripcion",
            color       = 0x2ECC71,
            campos      = campos_discord,
        )
    else:
        log(f"FALLO al subir {folder.name} — sin subido.txt, se reintentará.")
        discord_notify(
            titulo      = "Error al subir video",
            descripcion = f"Falló la subida de **{folder.name}**. Se reintentará en el próximo ciclo.",
            color       = 0xE74C3C,
        )

    return ok


# ══════════════════════════════════════════════════════════════════
# Generación de historia
# ══════════════════════════════════════════════════════════════════

def generar_historia() -> Path | None:
    """Corre horror_story_generator.py y retorna la carpeta nueva creada."""
    if not config.GENERATOR_SCRIPT.exists():
        log(f"ERROR: {config.GENERATOR_SCRIPT.name} no encontrado en {config.BASE_DIR}/")
        return None

    carpetas_antes = set(config.HISTORIAS_DIR.iterdir()) if config.HISTORIAS_DIR.exists() else set()

    log("No hay videos pendientes — generando nueva historia...")
    ok = run_streaming(config.GENERATOR_SCRIPT, cwd=config.BASE_DIR)

    if not ok:
        log("La generación terminó con error.")
        return None

    if config.HISTORIAS_DIR.exists():
        nuevas = [
            p for p in config.HISTORIAS_DIR.iterdir()
            if p.is_dir() and p not in carpetas_antes
        ]
        if nuevas:
            nueva = sorted(nuevas, key=lambda p: p.stat().st_ctime)[-1]
            log(f"Nueva historia detectada: {nueva.name}/")
            return nueva

    log("No se detectó carpeta nueva en historias/")
    return None


# ══════════════════════════════════════════════════════════════════
# Estado persistente (estado.json)
# ══════════════════════════════════════════════════════════════════

def leer_estado() -> dict:
    """Lee estado.json. Si no existe o está corrupto, devuelve estado vacío."""
    if config.STATE_FILE.exists():
        try:
            return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"ultimo_upload": 0, "ultimo_upload_legible": "nunca", "carpeta": ""}


def guardar_estado(carpeta: str):
    """Guarda el timestamp unix del momento actual como ultimo_upload."""
    ahora = time.time()
    data  = {
        "ultimo_upload":         ahora,
        "ultimo_upload_legible": datetime.fromtimestamp(ahora).strftime("%Y-%m-%d %H:%M:%S"),
        "carpeta":               carpeta,
    }
    config.STATE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log(f"estado.json actualizado — ultimo_upload: {data['ultimo_upload_legible']}")


def segundos_desde_ultimo_upload() -> float:
    """Devuelve cuántos segundos han pasado desde el último upload registrado."""
    estado = leer_estado()
    ts     = estado.get("ultimo_upload", 0)
    return time.time() - ts


def debe_subir_ahora() -> bool:
    """True si han pasado >= INTERVALO_HORAS desde el último upload."""
    diff_h = segundos_desde_ultimo_upload() / 3600
    if diff_h >= config.INTERVALO_HORAS:
        log(f"Han pasado {diff_h:.1f}h desde el último upload — es hora de subir.")
        return True
    proxima = datetime.fromtimestamp(
        leer_estado().get("ultimo_upload", 0) + config.INTERVALO_HORAS * 3600
    ).strftime("%Y-%m-%d %H:%M:%S")
    log(f"Solo han pasado {diff_h:.1f}h — esperando hasta {proxima}.")
    return False


# ══════════════════════════════════════════════════════════════════
# Ciclo principal
# ══════════════════════════════════════════════════════════════════

def ciclo():
    log("=" * 58)
    log("  AUTOMATIZADOR DE YOUTUBE SHORTS")
    log(f"  Intervalo : {config.INTERVALO_HORAS}h")
    log(f"  Scripts   : {config.BASE_DIR}/")
    log(f"  Historias : {config.HISTORIAS_DIR}/")
    log("=" * 58)

    estado_ini = leer_estado()
    if estado_ini["ultimo_upload"]:
        log(f"Último upload registrado: {estado_ini['ultimo_upload_legible']} (carpeta: {estado_ini['carpeta']})")
    else:
        log("No hay registro previo de uploads — se actuará en el primer ciclo.")

    while True:
        log("-" * 58)
        log("Inicio de ciclo")

        if not debe_subir_ahora():
            secs_pasados   = segundos_desde_ultimo_upload()
            secs_restantes = max(0, config.INTERVALO_HORAS * 3600 - secs_pasados)
            proxima = datetime.now() + timedelta(seconds=secs_restantes)
            log(f"Durmiendo {secs_restantes/60:.1f} min hasta {proxima.strftime('%Y-%m-%d %H:%M:%S')}...")
            time.sleep(secs_restantes)
            continue

        pendientes = get_pendientes()

        if pendientes:
            log(f"{len(pendientes)} video(s) pendiente(s) de subir.")
            ok = subir_video(pendientes[0])
            if ok:
                guardar_estado(pendientes[0].name)
        else:
            nueva = generar_historia()
            if nueva:
                if (nueva / "video.mp4").exists():
                    log("Video generado correctamente. Subiendo a YouTube...")
                    ok = subir_video(nueva)
                    if ok:
                        guardar_estado(nueva.name)
                else:
                    log(f"AVISO: video.mp4 no encontrado en {nueva.name}/ — se subirá en el próximo ciclo.")
            else:
                log("No se pudo generar historia. Se reintentará en 10 min...")
                time.sleep(600)
                continue

        proxima = datetime.now() + timedelta(hours=config.INTERVALO_HORAS)
        log(f"Ciclo completado. Próximo: {proxima.strftime('%Y-%m-%d %H:%M:%S')}")
        log(f"Durmiendo {config.INTERVALO_HORAS}h...")
        time.sleep(config.INTERVALO_HORAS * 3600)


# ══════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        ciclo()
    except KeyboardInterrupt:
        log("Automatizador detenido por el usuario (Ctrl+C).")