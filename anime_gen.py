#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
anime_gen.py
============
Generador de imágenes anime en formato vertical (9:16).
Modelo: zimage via pollinations.ai

Uso independiente:
    python anime_gen.py "una chica mirando el horizonte bajo la lluvia"
"""

import sys
import random
import urllib.parse

import requests
import urllib3

import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def build_prompt(user_prompt: str) -> str:
    """Añade el sufijo anime al prompt del usuario."""
    return user_prompt.strip().rstrip(",") + config.ANIME_SUFFIX


def generate(user_prompt: str, output_dir=None):
    """
    Genera una imagen anime y la guarda en output_dir.
    Retorna (path, seed).
    """
    from pathlib import Path

    output_dir = Path(output_dir) if output_dir else Path(".")

    if not config.POLLINATIONS_API_KEY:
        print("ERROR: POLLINATIONS_API_KEY no configurada en .env")
        sys.exit(1)

    prompt  = build_prompt(user_prompt)
    seed    = random.randint(1, 9_999_999)
    encoded = urllib.parse.quote(prompt)
    url     = f"https://gen.pollinations.ai/image/{encoded}"

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

    print(f"\n  Prompt  : {prompt[:110]}...")
    print(f"  Tamaño  : {config.IMAGE_WIDTH}x{config.IMAGE_HEIGHT}  (9:16 vertical)")
    print(f"  Modelo  : {config.IMAGE_MODEL}")
    print(f"  Seed    : {seed}")
    print("  Generando...\n")

    resp = requests.get(url, params=params, timeout=150, allow_redirects=True, verify=False)
    resp.raise_for_status()

    ctype = resp.headers.get("content-type", "")
    if "image" not in ctype:
        print(f"ERROR: Respuesta inesperada (content-type: {ctype})")
        print(resp.text[:400])
        sys.exit(1)

    data = resp.content
    if len(data) < 4000:
        print(f"ERROR: Imagen demasiado pequeña ({len(data)} bytes).")
        sys.exit(1)

    out_path = output_dir / f"anime_{seed}.png"
    out_path.write_bytes(data)

    return out_path, seed


def main():
    if len(sys.argv) < 2:
        print('Uso: python anime_gen.py "tu prompt aqui"')
        print('Ejemplo: python anime_gen.py "samurai bajo la lluvia en Tokio nocturno"')
        sys.exit(1)

    user_prompt = " ".join(sys.argv[1:])
    out_path, seed = generate(user_prompt)

    print(f"OK  Archivo : {out_path.resolve()}")
    print(f"    Seed    : {seed}")


if __name__ == "__main__":
    main()
