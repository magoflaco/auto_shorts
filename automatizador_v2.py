# -*- coding: utf-8 -*-
"""
automatizador_v2.py
===================
Orquestador multiplataforma de YouTube Shorts, Instagram Reels y TikTok.

Formato de subido.txt v2 (JSON):
{
  "version": 2,
  "carpeta": "...",
  "fecha_creacion": "ISO",
  "metadatos": {"titulo": "...", "descripcion": "..."},
  "plataformas": {
    "youtube":   {"subido": bool, "fecha": "ISO", "link": "...", "intentos": N, "ultimo_error": "..."},
    "instagram": {"subido": bool, "fecha": "ISO", "link": "...", "intentos": N, "ultimo_error": "..."},
    "tiktok":    {"subido": bool, "fecha": "ISO", "link": "...", "intentos": N, "ultimo_error": "..."}
  },
  "prompt": "...",
  "historia_extracto": "..."
}

Lógica principal:
  1. Busca carpetas con video.mp4
  2. Si tiene subido.txt antiguo (texto plano) → migra a v2, marca YT=OK
  3. Si tiene subido.txt v2 → reintenta plataformas faltantes (max 3 intentos c/u)
  4. Si no tiene subido.txt → sube a las 3 plataformas
  5. Si al menos una plataforma tiene TODOS los videos subidos → genera nuevo video
  6. Repite cada INTERVALO_HORAS
"""

import json
import subprocess
import sys
import time
import urllib.request
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from copy import deepcopy

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import config

# Importar funciones individuales del uploader
from video_uploader import (
    generar_metadatos_groq,
    subir_youtube,
    subir_instagram,
    subir_tiktok,
)

PLATAFORMAS = ["youtube", "instagram", "tiktok"]
MAX_INTENTOS = 3
MARKER = config.MARKER_FILE  # "subido.txt"


# ══════════════════════════════════════════════════════════════════
# Utilidades de log
# ══════════════════════════════════════════════════════════════════

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ══════════════════════════════════════════════════════════════════
# Discord (mejorado)
# ══════════════════════════════════════════════════════════════════

def discord_notify(titulo: str, descripcion: str, color: int = 0x9B59B6, campos: list = None):
    """Envía un embed a Discord via webhook."""
    if not config.DISCORD_WEBHOOK_URL:
        return

    embed = {
        "title":       titulo[:256],
        "description": (descripcion[:4090] + "...") if len(descripcion) > 4093 else descripcion,
        "color":       color,
        "timestamp":   datetime.utcnow().isoformat() + "Z",
        "footer":      {"text": "Auto Shorts v2"},
        "fields":      (campos or [])[:25],
    }
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    try:
        req = urllib.request.Request(
            config.DISCORD_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Python/auto_shorts"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"AVISO: Discord webhook falló: {e}")


def discord_reporte_subida(carpeta: str, estado: dict, es_nuevo: bool = False):
    """Envía un reporte detallado de subida a Discord."""
    plats = estado.get("plataformas", {})
    titulo_video = estado.get("metadatos", {}).get("titulo", carpeta)

    campos = [{"name": "📁 Carpeta", "value": carpeta, "inline": False}]

    todas_ok = True
    alguna_ok = False
    for p in PLATAFORMAS:
        info = plats.get(p, {})
        if info.get("subido"):
            emoji = "✅"
            valor = info.get("link") or "Subido"
            alguna_ok = True
        elif info.get("intentos", 0) >= MAX_INTENTOS:
            emoji = "❌"
            valor = f"FALLIDO ({info['intentos']} intentos)\n```{(info.get('ultimo_error') or 'Sin detalle')[:200]}```"
            todas_ok = False
        else:
            emoji = "⏳"
            valor = f"Pendiente (intento {info.get('intentos', 0)}/{MAX_INTENTOS})"
            if info.get("ultimo_error"):
                valor += f"\n```{info['ultimo_error'][:200]}```"
            todas_ok = False

        campos.append({"name": f"{emoji} {p.capitalize()}", "value": valor, "inline": True})

    if todas_ok:
        color = 0x2ECC71  # verde
        titulo = f"✅ Video completo: {titulo_video}"
    elif alguna_ok:
        color = 0xF39C12  # naranja
        titulo = f"⚠️ Video parcial: {titulo_video}"
    else:
        color = 0xE74C3C  # rojo
        titulo = f"❌ Video fallido: {titulo_video}"

    desc = estado.get("historia_extracto", "")[:300]
    if es_nuevo:
        desc = "🆕 **Nuevo video generado**\n" + desc

    discord_notify(titulo, desc, color, campos)


def discord_error(titulo: str, error: str, carpeta: str = ""):
    """Envía un reporte de error con stacktrace a Discord."""
    campos = []
    if carpeta:
        campos.append({"name": "Carpeta", "value": carpeta, "inline": False})
    campos.append({"name": "Error", "value": f"```{error[:1000]}```", "inline": False})
    discord_notify(f"🚨 {titulo}", "", 0xE74C3C, campos)


# ══════════════════════════════════════════════════════════════════
# Formato subido.txt v2
# ══════════════════════════════════════════════════════════════════

def _plataforma_vacia() -> dict:
    return {"subido": False, "fecha": None, "link": None, "intentos": 0, "ultimo_error": None}


def crear_estado_v2(carpeta: str, prompt: str = "", historia: str = "",
                    metadatos: dict = None) -> dict:
    """Crea un estado v2 vacío (nada subido aún)."""
    return {
        "version": 2,
        "carpeta": carpeta,
        "fecha_creacion": datetime.now().isoformat(),
        "metadatos": metadatos or {"titulo": "", "descripcion": ""},
        "plataformas": {p: _plataforma_vacia() for p in PLATAFORMAS},
        "prompt": prompt,
        "historia_extracto": historia[:500],
    }


def leer_subido(folder: Path) -> dict | None:
    """
    Lee subido.txt de una carpeta.
    Retorna:
      - dict v2 si existe y es parseable
      - dict v2 migrado si es formato antiguo (marca YT como subido)
      - None si no existe
    """
    marker_path = folder / MARKER
    if not marker_path.exists():
        return None

    contenido = marker_path.read_text(encoding="utf-8", errors="replace")

    # Intentar parsear como JSON (v2)
    try:
        data = json.loads(contenido)
        if data.get("version") == 2:
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Es formato antiguo (texto plano) → migrar a v2
    log(f"   Detectado subido.txt formato antiguo en {folder.name} → migrando a v2")
    estado = crear_estado_v2(folder.name)

    # El formato antiguo solo subía a YouTube, así que marcamos YT como subido
    estado["plataformas"]["youtube"]["subido"] = True
    estado["plataformas"]["youtube"]["fecha"] = datetime.now().isoformat()
    estado["plataformas"]["youtube"]["intentos"] = 1

    # Extraer link de YouTube del texto antiguo
    for line in contenido.splitlines():
        if "youtu.be/" in line or "youtube.com/watch" in line:
            for token in line.split():
                if "youtu" in token:
                    estado["plataformas"]["youtube"]["link"] = token.strip()
                    break

    # Extraer historia/prompt del texto antiguo si están
    if "--- PROMPT BASE ---" in contenido:
        try:
            estado["prompt"] = contenido.split("--- PROMPT BASE ---")[1].split("---")[0].strip()
        except Exception:
            pass
    if "--- HISTORIA" in contenido:
        try:
            estado["historia_extracto"] = contenido.split("--- HISTORIA")[1].split("---")[0].strip()[:500]
        except Exception:
            pass

    guardar_subido(folder, estado)
    return estado


def guardar_subido(folder: Path, estado: dict):
    """Guarda el estado v2 como JSON en subido.txt."""
    (folder / MARKER).write_text(
        json.dumps(estado, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ══════════════════════════════════════════════════════════════════
# Lógica de subida por plataforma
# ══════════════════════════════════════════════════════════════════

FUNCIONES_SUBIDA = {
    "youtube":   subir_youtube,
    "instagram": subir_instagram,
    "tiktok":    subir_tiktok,
}


def plataformas_pendientes(estado: dict) -> list:
    """Lista de plataformas que aún no están subidas y tienen < MAX_INTENTOS."""
    pendientes = []
    for p in PLATAFORMAS:
        info = estado["plataformas"].get(p, _plataforma_vacia())
        if not info.get("subido") and info.get("intentos", 0) < MAX_INTENTOS:
            pendientes.append(p)
    return pendientes


def plataformas_faltantes(estado: dict) -> list:
    """Lista de plataformas que NO están subidas (sin importar intentos)."""
    return [p for p in PLATAFORMAS if not estado["plataformas"].get(p, {}).get("subido")]


def intentar_subida(folder: Path, estado: dict, plataformas: list = None) -> dict:
    """
    Intenta subir a las plataformas indicadas (o las pendientes).
    Actualiza el estado en memoria y en disco.
    """
    if plataformas is None:
        plataformas = plataformas_pendientes(estado)

    if not plataformas:
        return estado

    video_path = str((folder / "video.mp4").resolve())
    json_path  = str((folder / "escenas.json").resolve())

    # Obtener metadatos si no los tenemos
    meta = estado.get("metadatos", {})
    titulo = meta.get("titulo", "")
    descripcion = meta.get("descripcion", "")

    if not titulo:
        try:
            log(f"   Generando metadatos con Groq para {folder.name}...")
            metadatos = generar_metadatos_groq(json_path)
            titulo = metadatos.get("titulo", "Historia de Terror")
            descripcion = metadatos.get("descripcion", "Una historia escalofriante. #Shorts #Reels #terror")
            estado["metadatos"] = {"titulo": titulo, "descripcion": descripcion}
        except Exception as e:
            log(f"   ERROR generando metadatos: {e}")
            titulo = "Historia de Terror"
            descripcion = "#Shorts #Reels #terror"

    for p in plataformas:
        info = estado["plataformas"].setdefault(p, _plataforma_vacia())
        if info.get("subido"):
            continue
        if info.get("intentos", 0) >= MAX_INTENTOS:
            continue

        log(f"   [{p.upper()}] Intentando subida (intento {info['intentos'] + 1}/{MAX_INTENTOS})...")
        info["intentos"] = info.get("intentos", 0) + 1

        try:
            func = FUNCIONES_SUBIDA[p]
            resultado = func(video_path, titulo, descripcion)

            if resultado["ok"]:
                info["subido"] = True
                info["fecha"] = datetime.now().isoformat()
                info["link"] = resultado.get("link")
                info["ultimo_error"] = None
                log(f"   [{p.upper()}] ✅ Subido OK: {resultado.get('link', '')}")
            else:
                info["ultimo_error"] = resultado.get("error", "Error desconocido")
                log(f"   [{p.upper()}] ❌ Falló: {info['ultimo_error'][:200]}")
        except Exception as e:
            info["ultimo_error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"
            log(f"   [{p.upper()}] ❌ Excepción: {info['ultimo_error'][:200]}")

        # Guardar después de cada intento (por si el proceso se interrumpe)
        guardar_subido(folder, estado)

    return estado


# ══════════════════════════════════════════════════════════════════
# Escaneo de carpetas
# ══════════════════════════════════════════════════════════════════

def escanear_historias() -> list:
    """
    Retorna lista de dicts con info de cada carpeta con video.mp4:
      {"folder": Path, "estado": dict|None, "tipo": "nuevo"|"antiguo"|"v2"}
    """
    if not config.HISTORIAS_DIR.exists():
        return []

    resultado = []
    for folder in sorted(config.HISTORIAS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        if not (folder / "video.mp4").exists():
            continue

        estado = leer_subido(folder)
        if estado is None:
            tipo = "nuevo"
        elif estado.get("version") == 2:
            tipo = "v2"
        else:
            tipo = "antiguo"  # Ya se migró a v2 en leer_subido()

        resultado.append({"folder": folder, "estado": estado, "tipo": tipo})

    return resultado


# ══════════════════════════════════════════════════════════════════
# Generación de historia
# ══════════════════════════════════════════════════════════════════

def run_streaming(script: Path, cwd: Path = None) -> bool:
    """Ejecuta un script Python mostrando su salida en tiempo real."""
    cwd = cwd or config.BASE_DIR
    log(f">> Ejecutando: {script.name}")
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
            log(f"<< {script.name} finalizó OK")
            return True
        log(f"<< {script.name} terminó con error (código {proc.returncode})")
        return False
    except Exception as e:
        log(f"<< ERROR ejecutando {script.name}: {e}")
        return False


def generar_historia() -> Path | None:
    """Corre horror_story_generator.py y retorna la carpeta nueva creada."""
    if not config.GENERATOR_SCRIPT.exists():
        log(f"ERROR: {config.GENERATOR_SCRIPT.name} no encontrado")
        return None

    carpetas_antes = set(config.HISTORIAS_DIR.iterdir()) if config.HISTORIAS_DIR.exists() else set()

    log("Generando nueva historia...")
    ok = run_streaming(config.GENERATOR_SCRIPT, cwd=config.BASE_DIR)

    if not ok:
        log("La generación terminó con error.")
        discord_error("Error al generar historia", "horror_story_generator.py terminó con código no-cero")
        return None

    if config.HISTORIAS_DIR.exists():
        nuevas = [p for p in config.HISTORIAS_DIR.iterdir() if p.is_dir() and p not in carpetas_antes]
        if nuevas:
            nueva = sorted(nuevas, key=lambda p: p.stat().st_ctime)[-1]
            log(f"Nueva historia detectada: {nueva.name}/")
            return nueva

    log("No se detectó carpeta nueva en historias/")
    return None


# ══════════════════════════════════════════════════════════════════
# Estado persistente (estado.json)
# ══════════════════════════════════════════════════════════════════

def leer_estado_global() -> dict:
    default_state = {
        "ultimo_upload": 0,
        "ultimo_upload_legible": "nunca",
        "carpeta": "",
        "errores_consecutivos": {"youtube": 0, "instagram": 0, "tiktok": 0}
    }
    if config.STATE_FILE.exists():
        try:
            data = json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
            for k, v in default_state.items():
                data.setdefault(k, v)
            if not isinstance(data.get("errores_consecutivos"), dict):
                data["errores_consecutivos"] = default_state["errores_consecutivos"]
            return data
        except Exception:
            pass
    return default_state


def guardar_estado_global(estado_dict: dict):
    config.STATE_FILE.write_text(json.dumps(estado_dict, indent=2, ensure_ascii=False), encoding="utf-8")


def actualizar_estado_upload(carpeta: str):
    estado = leer_estado_global()
    ahora = time.time()
    estado["ultimo_upload"] = ahora
    estado["ultimo_upload_legible"] = datetime.fromtimestamp(ahora).strftime("%Y-%m-%d %H:%M:%S")
    estado["carpeta"] = carpeta
    guardar_estado_global(estado)
    log(f"estado.json actualizado — {estado['ultimo_upload_legible']}")


def registrar_error_plataforma(p: str):
    estado = leer_estado_global()
    estado["errores_consecutivos"][p] = estado["errores_consecutivos"].get(p, 0) + 1
    guardar_estado_global(estado)
    if estado["errores_consecutivos"][p] == 5:
        msg = f"Plataforma {p.upper()} ha fallado 5 veces consecutivas y ha sido BLOQUEADA. Edite estado.json para poner sus errores en 0."
        log(f"🚫 {msg}")
        discord_error("Plataforma Bloqueada", msg)


def registrar_exito_plataforma(p: str):
    estado = leer_estado_global()
    if estado["errores_consecutivos"].get(p, 0) > 0:
        estado["errores_consecutivos"][p] = 0
        guardar_estado_global(estado)


def debe_subir_ahora() -> bool:
    estado = leer_estado_global()
    ts = estado.get("ultimo_upload", 0)
    diff_h = (time.time() - ts) / 3600
    if diff_h >= config.INTERVALO_HORAS:
        log(f"Han pasado {diff_h:.1f}h — es hora de actuar.")
        return True
    proxima = datetime.fromtimestamp(ts + config.INTERVALO_HORAS * 3600).strftime("%Y-%m-%d %H:%M:%S")
    log(f"Solo han pasado {diff_h:.1f}h — próximo ciclo: {proxima}")
    return False


# ══════════════════════════════════════════════════════════════════
# Lógica de decisión: ¿generar nuevo video?
# ══════════════════════════════════════════════════════════════════

def necesita_generacion(historias: list) -> bool:
    """
    Retorna True si debemos generar un nuevo video.

    Condiciones (OR):
      - No hay historias con video.mp4
      - Al menos una plataforma tiene TODOS los videos existentes subidos
        (es decir, ya no hay nada que subir ahí → necesitamos darle contenido nuevo)
    """
    if not historias:
        log("No hay historias con video.mp4 — se necesita generar.")
        return True

    # Para cada plataforma, contar cuántos videos tienen pendientes
    for p in PLATAFORMAS:
        pendientes_en_esta = 0
        for h in historias:
            estado = h.get("estado")
            if estado is None:
                # Sin subido.txt = pendiente para todas las plataformas
                pendientes_en_esta += 1
            elif not estado["plataformas"].get(p, {}).get("subido"):
                # Todavía no subido a esta plataforma (puede tener intentos agotados)
                if estado["plataformas"].get(p, {}).get("intentos", 0) < MAX_INTENTOS:
                    pendientes_en_esta += 1

        if pendientes_en_esta == 0:
            log(f"{p.capitalize()} tiene todos los videos subidos — se necesita generar nuevo contenido.")
            return True

    return False


# ══════════════════════════════════════════════════════════════════
# Ciclo principal
# ══════════════════════════════════════════════════════════════════

def encontrar_pendiente_para(historias: list, plataforma: str) -> dict | None:
    """
    Busca la PRIMERA carpeta que necesite subirse a esta plataforma específica.
    Retorna el dict de la historia o None.
    """
    for h in historias:
        estado = h.get("estado")
        if estado is None:
            return h  # Sin estado → necesita todas las plataformas
        info = estado["plataformas"].get(plataforma, {})
        if not info.get("subido") and info.get("intentos", 0) < MAX_INTENTOS:
            return h
    return None


def asegurar_estado(h: dict) -> dict:
    """
    Garantiza que una carpeta tenga un estado v2.
    Si no tiene subido.txt, crea uno vacío y lo guarda.
    Retorna el estado (existente o nuevo).
    """
    if h["estado"] is not None:
        return h["estado"]

    folder = h["folder"]
    prompt = ""
    historia_txt = ""
    json_path = folder / "escenas.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            prompt = data.get("story_prompt", "")
            historia_txt = data.get("historia", "")
        except Exception:
            pass

    estado = crear_estado_v2(folder.name, prompt, historia_txt)
    guardar_subido(folder, estado)
    h["estado"] = estado
    log(f"📝 Estado v2 creado para {folder.name}")
    return estado


def ciclo():
    log("=" * 60)
    log("  AUTOMATIZADOR v2 — MULTIPLATAFORMA")
    log(f"  Modo        : 1 subida POR PLATAFORMA por ciclo")
    log(f"  Plataformas : {', '.join(PLATAFORMAS)}")
    log(f"  Max intentos: {MAX_INTENTOS} por plataforma")
    log(f"  Intervalo   : {config.INTERVALO_HORAS}h")
    log(f"  Historias   : {config.HISTORIAS_DIR}/")
    log("=" * 60)

    estado_ini = leer_estado_global()
    if estado_ini["ultimo_upload"]:
        log(f"Último upload: {estado_ini['ultimo_upload_legible']} ({estado_ini['carpeta']})")
    else:
        log("Sin registro previo — se actuará inmediatamente.")

    discord_notify(
        "🚀 Automatizador v2 iniciado",
        f"Modo: 1 subida por plataforma por ciclo\nPlataformas: {', '.join(PLATAFORMAS)}\nIntervalo: {config.INTERVALO_HORAS}h",
        0x3498DB,
    )

    while True:
        log("-" * 60)
        log("Inicio de ciclo")

        if not debe_subir_ahora():
            ts = leer_estado_global().get("ultimo_upload", 0)
            secs_restantes = max(0, config.INTERVALO_HORAS * 3600 - (time.time() - ts))
            proxima = datetime.now() + timedelta(seconds=secs_restantes)
            log(f"Durmiendo {secs_restantes/60:.1f} min hasta {proxima.strftime('%H:%M:%S')}...")
            time.sleep(secs_restantes)
            continue

        # ── Paso 1: Escanear historias
        historias = escanear_historias()
        log(f"Historias encontradas: {len(historias)}")

        hubo_subida = False
        carpeta_procesada = ""
        plataformas_usadas = set()  # Plataformas que YA subieron algo en este ciclo
        carpetas_modificadas = set()

        # ── Paso 2: UNA subida por plataforma (colas independientes)
        estado_global = leer_estado_global()
        for p in PLATAFORMAS:
            if estado_global["errores_consecutivos"].get(p, 0) >= 5:
                log(f"[{p.upper()}] 🚫 BLOQUEADA (5 errores). Edita estado.json para reanudar.")
                continue

            h = encontrar_pendiente_para(historias, p)
            if h is None:
                log(f"[{p.upper()}] Sin videos pendientes.")
                continue

            plataformas_usadas.add(p)

            folder = h["folder"]
            estado = asegurar_estado(h)

            info_antes = deepcopy(estado["plataformas"].get(p, _plataforma_vacia()))

            log(f"[{p.upper()}] Subiendo: {folder.name}")
            estado = intentar_subida(folder, estado, [p])
            h["estado"] = estado

            info_despues = estado["plataformas"][p]
            if info_despues["subido"] and not info_antes.get("subido"):
                hubo_subida = True
                carpeta_procesada = folder.name
                registrar_exito_plataforma(p)
                log(f"[{p.upper()}] ✅ {folder.name} subido OK")
            else:
                err_msg = info_despues.get("ultimo_error", "Error desconocido")
                registrar_error_plataforma(p)
                log(f"[{p.upper()}] ❌ {folder.name} falló: {err_msg[:150]}")
                # Reportar error inmediatamente a Discord
                discord_error(
                    f"Fallo subiendo a {p.capitalize()}",
                    err_msg,
                    folder.name,
                )

            carpetas_modificadas.add(folder.name)

        # ── Discord: reporte resumen por cada carpeta tocada
        for nombre_carpeta in carpetas_modificadas:
            for h in historias:
                if h["folder"].name == nombre_carpeta and h["estado"]:
                    discord_reporte_subida(nombre_carpeta, h["estado"])
                    break

        # ── Paso 3: Generar video si alguna plataforma necesita contenido nuevo
        #    Esto se evalúa SIEMPRE, no depende de si hubo pendientes.
        #    Así YouTube recibe contenido nuevo aún cuando Instagram tenga 50 atrasados.
        historias = escanear_historias()

        if necesita_generacion(historias):
            nueva = generar_historia()
            if nueva and (nueva / "video.mp4").exists():
                log(f"Video generado: {nueva.name}")

                prompt = ""
                historia_txt = ""
                json_path = nueva / "escenas.json"
                if json_path.exists():
                    try:
                        data = json.loads(json_path.read_text(encoding="utf-8"))
                        prompt = data.get("story_prompt", "")
                        historia_txt = data.get("historia", "")
                    except Exception:
                        pass

                estado = crear_estado_v2(nueva.name, prompt, historia_txt)

                # Solo subir a plataformas que NO usaron su slot en paso 2 y no están bloqueadas
                estado_global = leer_estado_global()
                plataformas_disponibles = [
                    p for p in PLATAFORMAS 
                    if p not in plataformas_usadas and estado_global["errores_consecutivos"].get(p, 0) < 5
                ]
                if plataformas_disponibles:
                    log(f"Subiendo video nuevo a: {', '.join(plataformas_disponibles)}")
                    estado = intentar_subida(nueva, estado, plataformas_disponibles)
                    
                    # Registrar éxitos/fracasos para las que acabamos de intentar
                    for p_intentada in plataformas_disponibles:
                        if estado["plataformas"][p_intentada]["subido"]:
                            registrar_exito_plataforma(p_intentada)
                        else:
                            registrar_error_plataforma(p_intentada)
                else:
                    log("Todas las plataformas ya usaron su slot. El video nuevo se subirá en el próximo ciclo.")
                    guardar_subido(nueva, estado)

                discord_reporte_subida(nueva.name, estado, es_nuevo=True)

                alguna = any(estado["plataformas"][p]["subido"] for p in PLATAFORMAS)
                if alguna:
                    hubo_subida = True
                    carpeta_procesada = nueva.name
            elif nueva:
                log(f"AVISO: video.mp4 no encontrado en {nueva.name}/")
            else:
                log("No se pudo generar historia. Se reintentará en el próximo ciclo.")

        # ── Paso 4: Dormir
        if hubo_subida:
            actualizar_estado_upload(carpeta_procesada)
            proxima = datetime.now() + timedelta(hours=config.INTERVALO_HORAS)
            log(f"Ciclo completado. Próximo: {proxima.strftime('%Y-%m-%d %H:%M:%S')}")
            log(f"Durmiendo {config.INTERVALO_HORAS}h...")
            time.sleep(config.INTERVALO_HORAS * 3600)
        else:
            log("No hubo subidas exitosas. Reintentando en 10 min...")
            time.sleep(600)


# ══════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        ciclo()
    except KeyboardInterrupt:
        log("Detenido por el usuario (Ctrl+C).")
        discord_notify("⏹️ Automatizador detenido", "El usuario interrumpió el proceso.", 0x95A5A6)
    except Exception as e:
        tb = traceback.format_exc()
        log(f"ERROR FATAL: {e}\n{tb}")
        discord_error("Error fatal en el automatizador", tb)
        raise
