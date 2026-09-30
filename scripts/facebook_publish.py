"""
Publica un Reel en una Página de Facebook vía la Graph API de Video Reels de
Meta (distinta de la API de Instagram, aunque ambas son de la misma empresa).

Requiere las siguientes variables de entorno (GitHub Secrets):
  - FB_PAGE_ID            -> ID numérico de la Página de Facebook
  - FB_PAGE_ACCESS_TOKEN  -> Token de acceso de la Página (de larga duración)

IMPORTANTE: al igual que con Instagram, el video tiene que ser accesible por
una URL pública (no se manda el archivo directo) — este proyecto reutiliza el
raw.githubusercontent.com del propio repo (ver GUIA_CONFIGURACION.md).

A diferencia de Instagram, Facebook NO tiene un concepto de "Reel de prueba":
cualquier Reel publicado en la Página aparece de forma normal y permanente en
su pestaña de Reels. Por eso este módulo solo se usa UNA vez por video (no
dos como Instagram) — ver orchestrator.py.

Flujo de publicación (API de Reels de Facebook, 3 pasos + verificación):
  1. POST /{page-id}/video_reels  upload_phase=start
       -> devuelve video_id + upload_url
  2. POST https://rupload.facebook.com/video-upload/{video_id}
       (header "file_url" con la URL pública del video, en vez de mandar los
       bytes del archivo directo)
       -> confirma que Facebook pudo descargar el video
  3. POST /{page-id}/video_reels  upload_phase=finish, video_state=PUBLISHED
       -> encola la publicación
  4. GET /{video_id}?fields=status  (repetido cada pocos segundos)
       -> Meta no documenta con claridad todos los valores posibles de
          "video_status" para este endpoint; lo tratamos de forma genérica:
          mientras diga "processing" seguimos esperando, si aparece cualquier
          señal de error cortamos con un error, y en cualquier otro caso
          (una vez que deja de estar "processing") lo damos por publicado.
          Si en la primera prueba real el valor que aparece en el log no es
          ninguno de los dos casos previstos, avisale a Claude para afinar
          esta función con el dato real (está pensado para eso desde el
          diseño, no hace falta que funcione perfecto a la primera).
"""

import os
import sys
import time

import requests

API_VERSION = os.environ.get("FB_API_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{API_VERSION}"
UPLOAD_BASE = "https://rupload.facebook.com/video-upload"


def _page_id() -> str:
    return os.environ["FB_PAGE_ID"]


def _access_token() -> str:
    return os.environ["FB_PAGE_ACCESS_TOKEN"]


def _start_upload() -> str:
    """Inicia la sesión de subida. Devuelve el video_id."""
    resp = requests.post(
        f"{GRAPH_BASE}/{_page_id()}/video_reels",
        data={"upload_phase": "start", "access_token": _access_token()},
        timeout=60,
    )
    resp.raise_for_status()
    video_id = resp.json()["video_id"]
    print(f"[Facebook] Sesión de subida iniciada: {video_id}")
    return video_id


def _upload_by_url(video_id: str, video_url: str) -> None:
    """Le pasa a Facebook la URL pública del video para que lo descargue él
    mismo, en vez de mandarle los bytes del archivo directo."""
    resp = requests.post(
        f"{UPLOAD_BASE}/{video_id}",
        headers={
            "Authorization": f"OAuth {_access_token()}",
            "file_url": video_url,
        },
        timeout=120,
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success", False):
        raise RuntimeError(f"[Facebook] La subida por URL no fue confirmada: {body}")
    print(f"[Facebook] Video {video_id} descargado por Facebook desde la URL pública.")


def _finish(video_id: str, caption: str) -> None:
    """Le avisa a Facebook que ya se puede publicar el Reel."""
    resp = requests.post(
        f"{GRAPH_BASE}/{_page_id()}/video_reels",
        data={
            "video_id": video_id,
            "upload_phase": "finish",
            "video_state": "PUBLISHED",
            "description": caption or "",
            "access_token": _access_token(),
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success", False):
        raise RuntimeError(f"[Facebook] Facebook no confirmó la publicación: {body}")
    print(f"[Facebook] Reel {video_id} enviado a publicar.")


def _wait_until_ready(video_id: str, timeout_seconds: int = 300, poll_seconds: int = 10) -> None:
    """Espera a que Facebook termine de procesar/publicar el Reel.

    Ver la nota grande al principio del archivo: como Meta no documenta con
    precisión todos los valores posibles de "video_status", este chequeo es
    deliberadamente permisivo (solo trata "processing" como "seguir
    esperando" y cualquier mención de error como falla real).
    """
    elapsed = 0
    last_status = None
    while elapsed < timeout_seconds:
        resp = requests.get(
            f"{GRAPH_BASE}/{video_id}",
            params={"fields": "status", "access_token": _access_token()},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status", {})
        video_status = str(status.get("video_status", "")).lower()
        print(f"[Facebook] Estado del video {video_id}: {status}")

        if "error" in video_status or "fail" in video_status:
            raise RuntimeError(f"[Facebook] Falló el procesamiento del video {video_id}: {status}")

        if video_status and video_status != "processing":
            return

        last_status = video_status
        time.sleep(poll_seconds)
        elapsed += poll_seconds

    raise TimeoutError(
        f"[Facebook] El video {video_id} no terminó de procesar/publicar a tiempo "
        f"(último estado visto: '{last_status}')"
    )


def publish_reel(video_url: str, caption: str) -> str:
    """Flujo completo: iniciar, subir por URL, publicar, confirmar. Devuelve
    el video_id publicado."""
    video_id = _start_upload()
    _upload_by_url(video_id, video_url)
    _finish(video_id, caption)
    _wait_until_ready(video_id)
    print(f"[Facebook] Reel publicado en la Página: {video_id}")
    return video_id


if __name__ == "__main__":
    # Uso manual de prueba: python facebook_publish.py <video_url> "<caption>"
    if len(sys.argv) < 3:
        print('Uso: python facebook_publish.py <video_url> "<caption>"')
        sys.exit(1)
    publish_reel(sys.argv[1], sys.argv[2])
