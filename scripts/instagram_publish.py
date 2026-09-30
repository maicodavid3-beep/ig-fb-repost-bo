"""
Publica un Reel en Instagram vía la Instagram Graph API (Instagram Login).

Requiere las siguientes variables de entorno (GitHub Secrets):
  - IG_USER_ID       -> ID de tu cuenta profesional de Instagram
  - IG_ACCESS_TOKEN  -> Token de acceso de larga duración

IMPORTANTE: la API de Instagram necesita que el video sea accesible por una
URL PÚBLICA (no se puede mandar el archivo directo). Este proyecto usa el
raw.githubusercontent.com del propio repo como hosting del video (ver
GUIA_CONFIGURACION.md para el tradeoff de tener el repo público).

Endpoints usados (API version configurable, default v21.0):
  POST /{ig-user-id}/media          -> crea el contenedor (trial o normal)
  GET  /{container-id}              -> consulta status_code hasta FINISHED
  POST /{ig-user-id}/media_publish  -> publica el contenedor ya listo
"""

import os
import sys
import time

import requests

API_VERSION = os.environ.get("IG_API_VERSION", "v21.0")
BASE_URL = f"https://graph.instagram.com/{API_VERSION}"


def _ig_user_id():
    return os.environ["IG_USER_ID"]


def _access_token():
    return os.environ["IG_ACCESS_TOKEN"]


def create_container(video_url: str, caption: str, trial: bool) -> str:
    """Crea el contenedor de media. Devuelve el creation_id."""
    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption or "",
        "access_token": _access_token(),
    }
    if trial:
        payload["trial_params"] = {"graduation_strategy": "MANUAL"}

    resp = requests.post(f"{BASE_URL}/{_ig_user_id()}/media", json=payload, timeout=60)
    resp.raise_for_status()
    creation_id = resp.json()["id"]
    print(f"Contenedor creado ({'trial' if trial else 'normal'}): {creation_id}")
    return creation_id


def wait_until_ready(creation_id: str, timeout_seconds: int = 300, poll_seconds: int = 10) -> None:
    """Espera a que Instagram termine de procesar el video antes de publicar."""
    elapsed = 0
    while elapsed < timeout_seconds:
        resp = requests.get(
            f"{BASE_URL}/{creation_id}",
            params={"fields": "status_code", "access_token": _access_token()},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        print(f"Estado del contenedor {creation_id}: {status}")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram falló al procesar el contenedor {creation_id}")
        time.sleep(poll_seconds)
        elapsed += poll_seconds
    raise TimeoutError(f"El contenedor {creation_id} no terminó de procesar a tiempo")


def publish_container(creation_id: str) -> str:
    """Publica el contenedor ya procesado. Devuelve el media_id publicado."""
    resp = requests.post(
        f"{BASE_URL}/{_ig_user_id()}/media_publish",
        json={"creation_id": creation_id, "access_token": _access_token()},
        timeout=60,
    )
    resp.raise_for_status()
    media_id = resp.json()["id"]
    print(f"Publicado en Instagram: {media_id}")
    return media_id


def publish_reel(video_url: str, caption: str, trial: bool) -> str:
    """Flujo completo: crear contenedor, esperar, publicar. Devuelve el media_id."""
    creation_id = create_container(video_url, caption, trial=trial)
    wait_until_ready(creation_id)
    return publish_container(creation_id)


if __name__ == "__main__":
    # Uso manual de prueba: python instagram_publish.py <video_url> "<caption>" [trial|normal]
    if len(sys.argv) < 3:
        print('Uso: python instagram_publish.py <video_url> "<caption>" [trial|normal]')
        sys.exit(1)
    is_trial = len(sys.argv) > 3 and sys.argv[3] == "trial"
    publish_reel(sys.argv[1], sys.argv[2], trial=is_trial)
