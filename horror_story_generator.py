# -*- coding: utf-8 -*-
"""
horror_story_generator.py
=========================
Pipeline de generación de historias de terror:
  1. llama-3.1-8b-instant    -> prompt creativo único
  2. llama-3.3-70b-versatile -> historia (~1 min narración)
  3. llama-3.3-70b-versatile -> prompts de imagen por escena
  4. Deepgram TTS             -> narración en MP3
  5. pollinations.ai          -> una imagen anime por escena
  6. video_maker.py           -> video final con FFmpeg

Salida — una carpeta nueva por historia:
  historias/<nombre_escena_1>/
      escenas.json
      narracion.mp3
      escena_01.png ... escena_05.png
      musica.mp3   (opcional)
      video.mp4
"""

import asyncio
import aiohttp
import os
import re
import json
import random
import subprocess
import sys
import glob
import time
import urllib.parse
from pathlib import Path
from datetime import datetime

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import requests
import urllib3
from groq import AsyncGroq

import config

# ── Clientes Groq ────────────────────────────────────────────────
audio_client = AsyncGroq(api_key=config.GROQ_AUDIO_API_KEY)
chat_client  = AsyncGroq(api_key=config.GROQ_RESPONSE_API_KEY)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ══════════════════════════════════════════════════════════════════
# Utilidades de carpeta
# ══════════════════════════════════════════════════════════════════

def slugify(text: str, max_len: int = 50) -> str:
    """Convierte un texto en un nombre de carpeta válido y legible."""
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
        "ñ": "n", "Ñ": "N", "ü": "u", "Ü": "U",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^\w\s\-]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:max_len].strip("_")


def make_story_folder(first_scene_desc: str) -> Path:
    """Crea y devuelve la carpeta para esta historia."""
    name   = slugify(first_scene_desc) or f"historia_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    folder = config.HISTORIAS_DIR / name

    counter  = 1
    original = folder
    while folder.exists():
        folder = config.HISTORIAS_DIR / f"{original.name}_{counter}"
        counter += 1

    folder.mkdir(parents=True, exist_ok=True)
    print(f"   -> Carpeta creada: {folder}/")
    return folder


# ══════════════════════════════════════════════════════════════════
# Paso 1 — Prompt creativo único
# ══════════════════════════════════════════════════════════════════

async def generate_story_prompt() -> str:
    print("\n[1/5] Generando prompt creativo con llama-3.1-8b-instant...")

    completion = await chat_client.chat.completions.create(
        model=config.MODEL_SMALL,
        temperature=1.2,
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                "Genera un prompt UNICO y ORIGINAL para una historia de terror psicologico con elementos eroticos. "
                "El prompt debe incluir: un protagonista con nombre especifico, un lugar inusual, un elemento sobrenatural psicologico, "
                "y una tension erotica perturbadora. Se creativo y diferente cada vez. "
                "Responde SOLO con el prompt, sin explicaciones. Maximo 80 palabras. En espanol."
            ),
        }],
    )

    prompt = completion.choices[0].message.content.strip()
    print(f"   -> {prompt[:100]}...")
    return prompt


# ══════════════════════════════════════════════════════════════════
# Paso 2 — Historia completa
# ══════════════════════════════════════════════════════════════════

async def generate_story(story_prompt: str) -> str:
    print("\n[2/5] Escribiendo historia con llama-3.3-70b-versatile...")

    completion = await chat_client.chat.completions.create(
        model=config.MODEL_BIG,
        temperature=0.85,
        max_tokens=700,
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un escritor experto en horror psicologico latinoamericano con toques eroticos perturbadores. "
                    "Escribes en espanol rico y literario. Tus historias duran exactamente UN MINUTO al ser narradas en voz alta "
                    "(aproximadamente 130-150 palabras). No uses emojis ni asteriscos. "
                    "La historia debe tener: apertura intrigante, climax de tension erotica-psicologica, y un final perturbador. "
                    "NO uses subtitulos ni secciones. Escribe en prosa continua y fluida."
                ),
            },
            {
                "role": "user",
                "content": f"Escribe una historia de terror psicologico erotico basada en este prompt:\n\n{story_prompt}",
            },
        ],
    )

    story = completion.choices[0].message.content.strip()
    print(f"   -> {len(story.split())} palabras generadas")
    return story


# ══════════════════════════════════════════════════════════════════
# Paso 3 — Prompts de imagen por escena
# ══════════════════════════════════════════════════════════════════

def parse_delimited_scenes(raw: str) -> list:
    scenes = []
    blocks = re.split(r"###\s*SCENE\s*###", raw, flags=re.IGNORECASE)

    for block in blocks:
        block = block.strip()
        if len(block) < 10:
            continue

        sec_m  = re.search(r"SECONDS\s*[:\-]\s*(\d+)",             block, re.IGNORECASE)
        desc_m = re.search(r"DESC\s*[:\-]\s*(.+?)(?=\nPROMPT|\Z)", block, re.IGNORECASE | re.DOTALL)
        prom_m = re.search(r"PROMPT\s*[:\-]\s*(.+)",               block, re.IGNORECASE | re.DOTALL)

        if not prom_m:
            continue

        timestamp   = int(sec_m.group(1).strip()) if sec_m  else len(scenes) * 12
        description = desc_m.group(1).strip()      if desc_m else f"Escena {len(scenes)+1}"
        prompt      = prom_m.group(1).strip().strip('"').strip("'").strip()
        prompt      = " ".join(prompt.splitlines()).strip()

        scenes.append({
            "timestamp_seconds": timestamp,
            "scene_description": description,
            "image_prompt":      prompt,
        })

    return scenes


def fallback_extract_by_lines(raw: str) -> list:
    candidates = []
    for line in raw.splitlines():
        line = line.strip().strip('"').strip("'")
        if (len(line) > 60
                and "," in line
                and not re.match(r"^(SECONDS|DESC|PROMPT|###|Scene|Escena|\d+\.)", line, re.IGNORECASE)):
            candidates.append(line)

    scenes     = []
    timestamps = [0, 12, 24, 36, 48, 60]
    for i, prompt in enumerate(candidates[:6]):
        scenes.append({
            "timestamp_seconds": timestamps[i] if i < len(timestamps) else i * 10,
            "scene_description": f"Escena {i+1}",
            "image_prompt":      prompt,
        })
    return scenes


def emergency_fallback(story: str) -> list:
    words = story.split()
    chunk = max(1, len(words) // 5)
    style = "cinematic horror, psychological thriller, dark erotic tension, highly detailed, 8k, chiaroscuro lighting"
    scenes = []
    for i in range(5):
        fragment = " ".join(words[i * chunk : (i + 1) * chunk])
        scenes.append({
            "timestamp_seconds": i * 12,
            "scene_description": f"Escena {i+1}",
            "image_prompt":      f"Dark psychological horror scene: {fragment[:120]}, {style}",
        })
    return scenes


async def generate_image_prompts(story: str) -> list:
    print("\n[3/5] Generando prompts de imagen con llama-3.3-70b-versatile...")

    system_msg = (
        "You are an expert art director for psychological horror and dark cinema. "
        "You follow instructions exactly and respond ONLY in the format requested. "
        "Never add extra text, headers, explanations, or markdown outside the format.\n\n"
        "RULES FOR EVERY IMAGE PROMPT — follow all without exception:\n"
        "1. Write ALL prompts in ENGLISH only. Never use Spanish words.\n"
        "2. NEVER use character names (e.g. 'Alexandre', 'Elena', 'Juan'). "
        "Describe characters by visual appearance only: gender, age range, hair color/style, clothing, expression, body language.\n"
        "3. Every prompt MUST include a human subject physically present. Describe them first, then the environment.\n"
        "4. Make prompts cinematically rich: character appearance + pose + emotion + environment + lighting + mood + camera angle.\n"
        "5. Vary the framing across scenes: use wide shots, silhouettes, over-the-shoulder, low angle, close-up on hands/eyes, etc.\n"
        "6. Keep the ANIME_SUFFIX compatible style: avoid photorealism descriptors like 'photograph' or 'DSLR'.\n\n"
        "WRONG (uses name): 'Alexandre standing in dark hotel, horror atmosphere'\n"
        "WRONG (Spanish): 'Hombre de pie en lobby oscuro, iluminacion tenue'\n"
        "WRONG (no character): 'Decayed hotel lobby, broken chandeliers, eerie fog'\n"
        "CORRECT: 'A gaunt man in his thirties, long dark coat, frozen at the entrance of a decayed hotel lobby, "
        "cracked marble floors, shattered chandelier casting amber glow, wide shot, fog curling at his feet, "
        "cinematic horror, chiaroscuro lighting, 8k'"
    )

    user_msg = (
        "Read this horror story and create image generation prompts for 5 key scenes.\n\n"
        f"STORY:\n{story}\n\n"
        "Respond using EXACTLY this format -- copy the ###SCENE### marker for each scene:\n\n"
        "###SCENE###\n"
        "SECONDS: 0\n"
        "DESC: Breve descripcion de la escena en espanol (una sola linea)\n"
        "PROMPT: Woman standing at the entrance of an abandoned desert motel at dusk, cracked neon signs, eerie fog, cinematic horror, dark erotica, 8k, dramatic chiaroscuro lighting\n\n"
        "###SCENE###\n"
        "SECONDS: 12\n"
        "DESC: Segunda escena en espanol\n"
        "PROMPT: Your second prompt here, same style, no quotes\n\n"
        "###SCENE###\n"
        "SECONDS: 24\n"
        "DESC: Tercera escena en espanol\n"
        "PROMPT: Third prompt here\n\n"
        "###SCENE###\n"
        "SECONDS: 36\n"
        "DESC: Cuarta escena en espanol\n"
        "PROMPT: Fourth prompt here\n\n"
        "###SCENE###\n"
        "SECONDS: 48\n"
        "DESC: Quinta escena en espanol\n"
        "PROMPT: Fifth prompt here\n\n"
        "CRITICAL RULES:\n"
        "- Do NOT wrap prompts in quotes\n"
        "- Do NOT add any text before the first ###SCENE### or after the last PROMPT line\n"
        "- Keep each PROMPT on a single line\n"
        "- SECONDS must be a plain integer"
    )

    completion = await chat_client.chat.completions.create(
        model=config.MODEL_BIG,
        temperature=0.55,
        max_tokens=1600,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ],
    )

    raw    = completion.choices[0].message.content.strip()
    scenes = parse_delimited_scenes(raw)

    if len(scenes) >= 3:
        print(f"   -> {len(scenes)} escenas generadas OK")
        return scenes

    print(f"   ! Solo {len(scenes)} escenas detectadas, intentando extraccion por lineas...")
    scenes = fallback_extract_by_lines(raw)
    if len(scenes) >= 3:
        print(f"   -> {len(scenes)} escenas recuperadas por lineas OK")
        return scenes

    print("   ! Usando fallback de emergencia...")
    scenes = emergency_fallback(story)
    print(f"   -> {len(scenes)} escenas de emergencia generadas")
    return scenes


# ══════════════════════════════════════════════════════════════════
# Paso 4 — Narración con Deepgram TTS
# ══════════════════════════════════════════════════════════════════

async def narrate_story(story: str, output_path: Path) -> bool:
    print("\n[4/5] Narrando historia con Deepgram TTS...")

    tts_url = f"https://api.deepgram.com/v1/speak?model={config.VOICE_MODEL}"
    headers = {
        "Authorization": f"Token {config.DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(tts_url, json={"text": story}, headers=headers) as resp:
            if resp.status == 200:
                audio_bytes = await resp.read()
                output_path.write_bytes(audio_bytes)
                print(f"   -> narracion.mp3 ({len(audio_bytes) // 1024} KB)")
                return True
            else:
                print(f"   ERROR Deepgram ({resp.status}): {await resp.text()}")
                return False


# ══════════════════════════════════════════════════════════════════
# Paso 5 — Generación de imágenes anime via pollinations.ai
# ══════════════════════════════════════════════════════════════════

def generate_anime_image(image_prompt: str, output_path: Path) -> bool:
    """Genera una imagen anime vertical (9:16) y la guarda en output_path."""
    full_prompt = image_prompt.rstrip(",") + config.ANIME_SUFFIX
    seed        = random.randint(1, 9_999_999)
    encoded     = urllib.parse.quote(full_prompt)
    url         = f"https://gen.pollinations.ai/image/{encoded}"

    params = {
        "model":   config.IMAGE_MODEL,
        "width":   str(config.IMAGE_WIDTH),
        "height":  str(config.IMAGE_HEIGHT),
        "seed":    str(seed),
        "nologo":  "true",
        "enhance": "true",
        "safe":    "false",
        "key":     config.POLLINATIONS_API_KEY,
    }

    for attempt in range(1, 4):
        try:
            if attempt > 1:
                wait = attempt * 8
                print(f"      Reintento {attempt}/3 (esperando {wait}s)...")
                time.sleep(wait)
                params["seed"] = str(random.randint(1, 9_999_999))

            resp = requests.get(url, params=params, timeout=180, allow_redirects=True, verify=False)
            resp.raise_for_status()

            ctype = resp.headers.get("content-type", "")
            if "image" not in ctype:
                print(f"      Intento {attempt}: content-type inesperado ({ctype}), reintentando...")
                continue

            data = resp.content
            if len(data) < 4000:
                print(f"      Intento {attempt}: imagen muy pequeña ({len(data)} bytes), reintentando...")
                continue

            output_path.write_bytes(data)
            return True

        except Exception as e:
            print(f"      Intento {attempt} falló: {e}")

    print("      ERROR: la imagen no pudo generarse tras 3 intentos")
    return False


async def generate_all_images(scenes: list, folder: Path) -> list:
    """Genera una imagen anime por cada escena secuencialmente."""
    print(f"\n[5/5] Generando {len(scenes)} imágenes anime con pollinations.ai...")

    loop = asyncio.get_event_loop()

    for i, scene in enumerate(scenes, 1):
        filename   = f"escena_{i:02d}.png"
        out_path   = folder / filename
        desc_short = scene["scene_description"][:50]

        print(f"   [{i}/{len(scenes)}] {desc_short}...")

        ok = await loop.run_in_executor(
            None,
            generate_anime_image,
            scene["image_prompt"],
            out_path,
        )

        if ok:
            scene["image_file"] = filename
            size_kb = out_path.stat().st_size // 1024
            print(f"          -> {filename} ({size_kb} KB) OK")
        else:
            scene["image_file"] = None
            print(f"          -> {filename} FALLO (se continúa con la siguiente)")

    return scenes


# ══════════════════════════════════════════════════════════════════
# Guardar JSON con metadata
# ══════════════════════════════════════════════════════════════════

def save_json(story_prompt: str, story: str, scenes: list, folder: Path):
    data = {
        "generado":      datetime.now().isoformat(),
        "story_prompt":  story_prompt,
        "historia":      story,
        "total_escenas": len(scenes),
        "escenas": [
            {
                "numero":            i,
                "timestamp_seconds": s["timestamp_seconds"],
                "scene_description": s["scene_description"],
                "image_prompt":      s["image_prompt"],
                "image_file":        s.get("image_file"),
            }
            for i, s in enumerate(scenes, 1)
        ],
    }

    json_path = folder / "escenas.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("   -> escenas.json guardado")
    return json_path


# ══════════════════════════════════════════════════════════════════
# Pipeline principal
# ══════════════════════════════════════════════════════════════════

async def main():
    print("\n" + "=" * 60)
    print("  GENERADOR DE HORROR PSICOLOGICO EROTICO  v4")
    print("  Groq LLaMA -> Deepgram TTS -> Anime Images")
    print("=" * 60)

    # Pasos 1 y 2: texto
    story_prompt = await generate_story_prompt()
    story        = await generate_story(story_prompt)

    # Paso 3: prompts de escena
    scenes = await generate_image_prompts(story)

    # Crear carpeta
    first_desc = scenes[0]["scene_description"] if scenes else "historia"
    folder     = make_story_folder(first_desc)

    # Pasos 4 y 5 en paralelo
    tts_path = folder / "narracion.mp3"

    tts_task    = asyncio.create_task(narrate_story(story, tts_path))
    images_task = asyncio.create_task(generate_all_images(scenes, folder))

    tts_ok, scenes = await asyncio.gather(tts_task, images_task)

    # Guardar JSON
    json_path = save_json(story_prompt, story, scenes, folder)

    # Paso 6: Descargar música y generar video
    video_ok   = False
    video_path = folder / "video.mp4"

    if not config.VIDEO_MAKER.exists():
        print(f"\n[6/6] AVISO: video_maker.py no encontrado en {config.BASE_DIR}/")
    else:
        # 6a. Descargar música de fondo
        musica_path = folder / "musica.mp3"
        musica_ok   = False

        if not config.MUSIC_DOWNLOADER.exists():
            print("\n[6/6] AVISO: music_downloader.py no encontrado — video sin música.")
        else:
            print("\n[6/6] Descargando música de fondo...")
            mp3_antes = set(glob.glob(str(folder / "*.mp3")))
            try:
                r = subprocess.run(
                    [sys.executable, str(config.MUSIC_DOWNLOADER)],
                    cwd=str(folder),
                    capture_output=True, text=True, encoding="utf-8",
                )
                mp3_despues = set(glob.glob(str(folder / "*.mp3")))
                nuevos = mp3_despues - mp3_antes

                if nuevos:
                    descargado = Path(list(nuevos)[0])
                    if musica_path.exists():
                        musica_path.unlink()
                    descargado.rename(musica_path)
                    size_kb = musica_path.stat().st_size // 1024
                    print(f"   -> musica.mp3 ({size_kb} KB) OK")
                    musica_ok = True
                elif musica_path.exists():
                    musica_ok = True
                    print("   -> musica.mp3 ya existía, reutilizando")
                else:
                    print("   AVISO: music_downloader no produjo ningún mp3 nuevo")
                    err = (r.stderr or "").strip().splitlines()
                    for line in err[-4:]:
                        print(f"      {line}")
            except Exception as e:
                print(f"   ERROR al descargar música: {e}")

        # 6b. Generar video
        label = "  (con música)" if musica_ok else "  (sin música)"
        print(f"\n   Renderizando video{label}...")
        try:
            result = subprocess.run(
                [sys.executable, str(config.VIDEO_MAKER)],
                cwd=str(folder),
                capture_output=True, text=True, encoding="utf-8",
            )
            if result.returncode == 0 and video_path.exists():
                video_ok = True
                size_mb  = video_path.stat().st_size // (1024 * 1024)
                print(f"   -> video.mp4 ({size_mb} MB) OK")
            else:
                print("   video.mp4 FALLO — revisa que ffmpeg esté instalado y en el PATH.")
                err_lines = (result.stderr or result.stdout or "").strip().splitlines()
                for line in err_lines[-8:]:
                    print(f"      {line}")
        except Exception as e:
            print(f"   ERROR inesperado al llamar video_maker.py: {e}")

    # Resumen final
    img_ok   = sum(1 for s in scenes if s.get("image_file"))
    img_fail = len(scenes) - img_ok

    print("\n" + "=" * 60)
    print("  COMPLETADO")
    print("=" * 60)
    print(f"  Carpeta  : {folder.resolve()}/")
    print(f"  Audio    : {'narracion.mp3  OK' if tts_ok else 'narracion.mp3  FALLO'}")
    print(f"  Imágenes : {img_ok}/{len(scenes)} generadas" + (f"  ({img_fail} fallaron)" if img_fail else "  OK"))
    print(f"  Música   : {'musica.mp3  OK' if (folder / 'musica.mp3').exists() else 'musica.mp3  NO GENERADA'}")
    print(f"  JSON     : escenas.json")
    print(f"  Video    : {'video.mp4  OK' if video_ok else 'video.mp4  FALLO'}")
    print(f"\n  Archivos en {folder}/")
    for f in sorted(folder.iterdir()):
        size = f.stat().st_size // 1024
        print(f"    {f.name:<25} {size:>5} KB")
    print()


if __name__ == "__main__":
    asyncio.run(main())
