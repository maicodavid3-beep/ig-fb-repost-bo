"""
Orquestador del posteo con demora de 24 horas entre el Trial Reel de
Instagram y su Reel normal + el posteo en la Página de Facebook.

Esta es una copia adaptada del bot original de TikTok -> YouTube + Instagram
(repo tiktok-repost-bot), pensada para una cuenta donde NO hace falta subir a
YouTube, pero sí replicar el contenido en una Página de Facebook además de
Instagram.

Cada corrida programada ejecuta un "ciclo" completo que hace dos cosas, en
este orden:

1. Revisa state/pending_normal.json (videos que ya tienen su Trial Reel de
   Instagram publicado) y, de los que ya cumplieron sus 24 horas de espera:
     - publica el Reel normal correspondiente en Instagram (Fase 2), y
     - publica ESE MISMO video como Reel en la Página de Facebook.
   Facebook no tiene concepto de "Reel de prueba" (cualquier Reel publicado
   ahí aparece de forma normal y permanente), así que se publica ahí una sola
   vez por video -junto con el Reel normal de Instagram-, no dos veces.
   Los que todavía no cumplieron las 24 horas se dejan esperando para la
   próxima corrida (no se tocan).
2. Toma el próximo video "pending" de config/queue.json (con su archivo ya
   subido) y publica su Trial Reel en Instagram (Fase 1), guardando en
   state/pending_normal.json la marca de tiempo exacta en que se publicó el
   trial, para poder calcular después cuándo le toca su Fase 2 (24hs más
   tarde).

Se ejecuta desde GitHub Actions, que llama normalmente:
    python scripts/orchestrator.py ciclo

También se pueden forzar las fases por separado para pruebas manuales
(workflow_dispatch), aunque el uso normal en el horario programado es
siempre "ciclo":
    python scripts/orchestrator.py fase1   # fuerza solo un trial nuevo
    python scripts/orchestrator.py fase2   # fuerza la publicación de TODOS
                                            # los que estén esperando, SIN
                                            # esperar las 24hs (útil para
                                            # probar manualmente)

PROTECCIÓN CONTRA DISPAROS DUPLICADOS: como hay dos disparadores en paralelo
(el cron nativo de GitHub Actions + el respaldo externo de cron-job.org),
puede pasar que los dos disparen casi al mismo horario. Para que eso no
duplique el procesamiento, cada modo registra en state/last_run.json cuándo
corrió por última vez, y si ya corrió hace menos de RECENT_RUN_MINUTES
minutos, la corrida nueva no hace nada (asume que es un disparo duplicado
del mismo horario, no un horario nuevo).
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from facebook_publish import publish_reel as publish_facebook_reel  # noqa: E402
from instagram_publish import publish_reel as publish_instagram_reel  # noqa: E402

ROOT = Path(__file__).parent.parent
QUEUE_PATH = ROOT / "config" / "queue.json"
PENDING_PATH = ROOT / "state" / "pending_normal.json"
LAST_RUN_PATH = ROOT / "state" / "last_run.json"

# Cuánto tiempo tiene que pasar desde el Trial Reel para publicar el Reel
# normal (Instagram) + el posteo en Facebook del mismo video.
NORMAL_DELAY = timedelta(hours=24)

# Margen de tolerancia para no perderse el horario que le toca a un video
# por unos minutos de atraso/adelanto del disparador (GitHub Actions es
# "best effort" y puede atrasarse un poco). Un video se considera "listo"
# un poco antes de cumplir las 24hs exactas de esta manera.
NORMAL_DELAY_TOLERANCE = timedelta(minutes=15)

# Si en una misma corrida hay que publicar más de un video acumulado (por
# ejemplo tras una corrida perdida), esperamos esto entre uno y otro para
# que no salgan pegados.
BACKLOG_GAP_SECONDS = 15 * 60

# Ventana de "esto es probablemente un disparo duplicado del mismo horario".
RECENT_RUN_MINUTES = 110


def _video_public_url(file_relative_path: str) -> str:
    """Construye la URL pública raw.githubusercontent.com del video.

    Requiere que el repo sea PÚBLICO (ver GUIA_CONFIGURACION.md) y que el
    video ya esté commiteado en la rama principal antes de que corra
    esta fase.
    """
    repo = os.environ["GITHUB_REPOSITORY"]  # ej: "usuario/ig-fb-repost-bot"
    branch = os.environ.get("GITHUB_BRANCH", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{file_relative_path}"


def _load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _recently_ran(key: str) -> bool:
    """True si esta clave (ciclo/fase1/fase2) ya se ejecutó hace menos de
    RECENT_RUN_MINUTES."""
    data = _load_json(LAST_RUN_PATH, default={}) or {}
    ts = data.get(key)
    if not ts:
        return False
    try:
        last = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (_now() - last) < timedelta(minutes=RECENT_RUN_MINUTES)


def _mark_ran(key: str) -> None:
    data = _load_json(LAST_RUN_PATH, default={}) or {}
    data[key] = _now().isoformat()
    _save_json(LAST_RUN_PATH, data)


def _is_due(pending_item: dict, force: bool = False) -> bool:
    """True si a este video ya le toca su Reel normal + su posteo en Facebook."""
    if force:
        return True
    ts = pending_item.get("trial_posted_at")
    if not ts:
        print(
            f"Aviso: {pending_item.get('id')} no tiene 'trial_posted_at' "
            "guardado. Se publica ahora en vez de esperar 24hs."
        )
        return True
    try:
        posted_at = datetime.fromisoformat(ts)
    except ValueError:
        return True
    return (_now() - posted_at) >= (NORMAL_DELAY - NORMAL_DELAY_TOLERANCE)


def _do_fase1() -> None:
    queue = _load_json(QUEUE_PATH)

    siguiente = next(
        (v for v in queue if v["status"] == "pending" and (ROOT / v["file"]).exists()),
        None,
    )
    if siguiente is None:
        print(
            "[Fase 1] No hay videos pendientes en la cola (o están pending "
            "pero el archivo todavía no fue subido). Nada que hacer."
        )
        return

    video_url = _video_public_url(siguiente["file"])
    caption = siguiente["caption"]

    print(f"[Fase 1] Procesando video {siguiente['id']} ({siguiente['file']})")

    ig_trial_id = publish_instagram_reel(video_url=video_url, caption=caption, trial=True)

    siguiente["status"] = "trial_posted"
    siguiente["ig_trial_media_id"] = ig_trial_id
    _save_json(QUEUE_PATH, queue)

    # IMPORTANTE: agregamos a la lista (no sobreescribimos), así si alguna
    # vez queda más de un video esperando su Fase 2, no se pierde ninguno.
    # Guardamos también trial_posted_at para poder calcular cuándo le toca
    # su Reel normal + su posteo en Facebook (24hs después de este momento).
    pendientes = _load_json(PENDING_PATH, default=[]) or []
    pendientes.append(
        {
            "id": siguiente["id"],
            "video_url": video_url,
            "caption": caption,
            "trial_posted_at": _now().isoformat(),
        }
    )
    _save_json(PENDING_PATH, pendientes)

    print(
        f"[Fase 1] Trial Reel publicado en Instagram para {siguiente['id']}. "
        "Su Reel normal (Instagram) y su posteo en Facebook van a salir en ~24hs."
    )


def _do_fase2(force: bool = False) -> None:
    pendientes = _load_json(PENDING_PATH, default=[]) or []

    if not pendientes:
        print("[Fase 2] No hay ningún video esperando su publicación normal. Nada que hacer.")
        return

    listos = [p for p in pendientes if _is_due(p, force=force)]
    no_listos = [p for p in pendientes if not _is_due(p, force=force)]

    if not listos:
        print(
            f"[Fase 2] Hay {len(pendientes)} video(s) esperando su turno, "
            "pero ninguno cumplió todavía sus 24hs. No se publica nada en "
            "esta corrida."
        )
        return

    queue = _load_json(QUEUE_PATH)
    publicados = []

    # "restantes" es lo que va a terminar en pending_normal.json: arranca
    # con TODO lo que no se procesa en este for (los no_listos) más los
    # listos que todavía no llegamos a publicar. A medida que cada uno se
    # publica de verdad, lo sacamos de acá y guardamos enseguida (ver abajo)
    # — NO esperamos a que termine todo el lote para guardar.
    restantes = list(no_listos) + list(listos)

    # Procesamos TODOS los que ya estén listos (no solo el primero), por si
    # se acumuló más de uno (por ejemplo tras una corrida perdida). Si hay
    # más de uno, los espaciamos un poco entre sí.
    for idx, pending in enumerate(listos):
        item = next((v for v in queue if v["id"] == pending["id"]), None)
        if item is None:
            print(f"Aviso: no se encontró en la cola el video {pending['id']}. Lo descarto de la lista de espera.")
            restantes = [p for p in restantes if p["id"] != pending["id"]]
            continue

        if idx > 0:
            print(f"[Fase 2] Esperando {BACKLOG_GAP_SECONDS // 60} min antes de publicar el siguiente...")
            time.sleep(BACKLOG_GAP_SECONDS)

        ig_normal_id = publish_instagram_reel(video_url=pending["video_url"], caption=pending["caption"], trial=False)
        fb_video_id = publish_facebook_reel(video_url=pending["video_url"], caption=pending["caption"])

        item["status"] = "done"
        item["ig_normal_media_id"] = ig_normal_id
        item["fb_video_id"] = fb_video_id
        publicados.append(pending["id"])
        print(f"[Fase 2] Reel normal (Instagram) y posteo en Facebook publicados para {pending['id']}.")

        # IMPORTANTE: guardamos INMEDIATAMENTE después de cada publicación
        # real, no recién al final del lote. Si el proceso se corta a mitad
        # de un lote con varios videos pendientes, lo que ya se publicó de
        # verdad queda registrado y la próxima corrida no lo vuelve a
        # publicar.
        restantes = [p for p in restantes if p["id"] != pending["id"]]
        _save_json(QUEUE_PATH, queue)
        _save_json(PENDING_PATH, restantes)

    if len(publicados) > 1:
        print(
            f"Nota: se publicaron {len(publicados)} video(s) en esta "
            f"corrida: {', '.join(publicados)}"
        )
    if no_listos:
        print(
            f"Quedan {len(no_listos)} video(s) esperando a cumplir sus 24hs: "
            f"{', '.join(p['id'] for p in no_listos)}"
        )


def ciclo() -> None:
    """Modo normal, usado por el horario programado: revisa si hay algún
    video que ya cumplió sus 24hs (y lo publica en Instagram + Facebook), y
    después sube el próximo Trial Reel nuevo a Instagram."""
    if _recently_ran("ciclo"):
        print(
            f"El ciclo ya se ejecutó hace menos de {RECENT_RUN_MINUTES} minutos. "
            "Esto es probablemente un disparo duplicado del mismo horario "
            "(cron nativo de GitHub + respaldo de cron-job.org). No hago nada."
        )
        return

    _do_fase2(force=False)
    _do_fase1()
    _mark_ran("ciclo")


def fase1() -> None:
    """Fuerza SOLO la Fase 1 (subir un trial nuevo a Instagram). Pensado
    para pruebas manuales desde 'Run workflow', no para el horario
    programado."""
    if _recently_ran("fase1"):
        print(f"Fase 1 (manual) ya se ejecutó hace menos de {RECENT_RUN_MINUTES} minutos. No hago nada.")
        return
    _do_fase1()
    _mark_ran("fase1")


def fase2() -> None:
    """Fuerza la Fase 2 para TODOS los que estén esperando, sin importar si
    ya cumplieron las 24hs o no. Pensado para pruebas manuales desde 'Run
    workflow', no para el horario programado."""
    if _recently_ran("fase2"):
        print(f"Fase 2 (manual) ya se ejecutó hace menos de {RECENT_RUN_MINUTES} minutos. No hago nada.")
        return
    _do_fase2(force=True)
    _mark_ran("fase2")


def claim(key: str) -> None:
    """Usado por el workflow de GitHub Actions para "reservar" el turno
    ANTES de hacer ningún trabajo real (publicar en Instagram/Facebook).

    Si esta clave (ciclo/fase1/fase2) ya se reservó/ejecutó hace menos de
    RECENT_RUN_MINUTES, termina con código de salida 2 (le avisa al workflow
    que tiene que saltear esta corrida) sin modificar nada. Si no, marca la
    clave como "reservada ahora" en state/last_run.json y termina con
    código 0; el workflow va a intentar commitear y pushear ese cambio de
    inmediato, ANTES de tocar cualquier API real.
    """
    if _recently_ran(key):
        print(
            f"'{key}' ya se reservó/ejecutó hace menos de {RECENT_RUN_MINUTES} "
            "minutos. Salteo esta corrida antes de hacer ningún trabajo real."
        )
        sys.exit(2)
    _mark_ran(key)
    print(f"Turno '{key}' reservado. Sigue el resto de la corrida.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("ciclo", "fase1", "fase2", "claim"):
        print("Uso: python orchestrator.py [ciclo|fase1|fase2|claim <clave>]")
        sys.exit(1)

    if sys.argv[1] == "claim":
        if len(sys.argv) != 3:
            print("Uso: python orchestrator.py claim [ciclo|fase1|fase2]")
            sys.exit(1)
        claim(sys.argv[2])
    else:
        {"ciclo": ciclo, "fase1": fase1, "fase2": fase2}[sys.argv[1]]()
