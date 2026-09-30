# Guía de configuración — Repost bot Instagram + Facebook

Esta es la versión hermana del bot original (`tiktok-repost-bot`, que sube a
YouTube + Instagram), adaptada para una cuenta donde **no hace falta YouTube**
pero sí querés que cada video se publique en Instagram **y** en una Página de
Facebook. Es un repositorio completamente aparte: corre solo, con sus propias
credenciales y su propia cola de videos, sin tocar para nada al otro bot.

Tiempo estimado: 20-30 minutos (más corto que el original porque no hay que
tocar Google Cloud/YouTube, y la cuenta de Instagram/Facebook ya la tenés
armada).

---

## 0. Cómo funciona, en criollo

- Vos ponés los videos y sus descripciones en una "cola" (`config/queue.json`), igual que en el otro bot.
- 4 veces al día, GitHub corre un "ciclo" automático que hace dos cosas:
  - **Fase 2**: si algún video ya cumplió **24 horas** desde que se publicó su Trial Reel en Instagram, publica ese mismo video como Reel normal en Instagram **y, al mismo tiempo, lo publica una vez en tu Página de Facebook**.
  - **Fase 1**: agarra el próximo video pendiente de la cola y publica su Trial Reel en Instagram (a este le va a tocar su Fase 2 dentro de 24hs).
- El bot va marcando en `config/queue.json` qué videos ya se publicaron en cada lugar.

**Diferencia importante con Instagram:** Facebook no tiene el concepto de
"Reel de prueba". Cualquier Reel que se publica en una Página aparece de
forma normal y permanente en su pestaña de Reels. Por eso este bot publica
cada video en Facebook **una sola vez** (junto con el Reel normal de
Instagram, a las 24hs), no dos veces como hace con Instagram — publicar el
mismo video dos veces en la misma Página se vería como contenido repetido.

**Importante sobre privacidad:** igual que el otro bot, para que Instagram y
Facebook puedan descargar el video y publicarlo, tiene que estar en una URL
pública. Este proyecto usa tu propio repositorio de GitHub como hosting
(tiene que ser un repo **público**).

---

## 1. Preparar los videos

Igual que en el otro bot: descargalos de TikTok (o de donde sea el contenido
original) sin marca de agua, y guardá la descripción/caption exacta de cada
uno.

---

## 2. Crear el repositorio en GitHub

1. Creá un repositorio nuevo, **público**, por ejemplo `ig-fb-repost-bot` (para no confundirlo con el otro).
2. Subí ahí toda la carpeta que te mandé.
3. Poné tus videos dentro de la carpeta `videos/` (nombres simples, sin espacios: `video-001.mp4`, `video-002.mp4`, etc.).
4. Editá `config/queue.json` y agregá una entrada por cada video:

```json
[
  {
    "id": "video-001",
    "file": "videos/video-001.mp4",
    "caption": "Así arranca tu semana 💪 #motivacion",
    "status": "pending",
    "ig_trial_media_id": null,
    "ig_normal_media_id": null,
    "fb_video_id": null
  }
]
```

---

## 3. Instagram (igual que en el otro bot)

Como ya tenés la cuenta de Instagram Business conectada a su Facebook Page,
este paso es sobre todo generar el token de acceso para ESTA automatización
en particular (aunque sea la misma cuenta de Instagram que ya usás en el
bot original, este repo necesita su propia copia del token):

1. Andá a [developers.facebook.com](https://developers.facebook.com) → tu app (podés reutilizar la misma app que ya usaste para el bot original, o crear una nueva — cualquiera de las dos funciona).
2. Dentro de la app, sección **Instagram** (Instagram API con Instagram Login), generá o confirmá:
   - `IG_USER_ID`: el ID numérico de la cuenta de Instagram.
   - `IG_ACCESS_TOKEN`: un token de larga duración (60 días).

**Ojo con la fecha de vencimiento:** vence a los 60 días, igual que en el bot original. Poné un recordatorio a los ~50 días.

---

## 4. Facebook (nuevo — no estaba en el bot original)

Esta parte es la única realmente nueva respecto al bot de YouTube+Instagram.
Vas a necesitar un **token de acceso de la Página** (distinto del token de
Instagram, aunque se gestionan desde la misma app de Meta).

### 4.1. Permisos que necesita la app

En la misma app de [developers.facebook.com](https://developers.facebook.com)
que usás para Instagram, asegurate de tener (o agregar) estos permisos para
publicar Reels en la Página:

- `pages_show_list`
- `pages_read_engagement`
- `pages_manage_posts`

Si la app ya está en modo "Live" (producción) y estos permisos no estaban
antes en uso, es posible que Meta pida una revisión adicional para
habilitarlos formalmente. Para páginas que administrás vos mismo esto suele
resolverse sin mayor trámite, pero si te aparece algún bloqueo avisame y lo
vemos juntos — Meta cambia estas reglas seguido.

### 4.2. Conseguir el `FB_PAGE_ID`

1. Andá a tu Página de Facebook → **Configuración** → **General** (o "Acerca de"): ahí figura el **Page ID** (un número).

### 4.3. Conseguir el `FB_PAGE_ACCESS_TOKEN`

1. Andá a [Graph API Explorer](https://developers.facebook.com/tools/explorer/) y elegí tu app arriba a la derecha.
2. En **"User or Page"**, dejalo en modo Usuario por ahora. En **"Permissions"**, agregá `pages_show_list`, `pages_read_engagement` y `pages_manage_posts`, y generá el **Access Token** (token de usuario).
3. Ese token de usuario dura poco (horas). Para conseguir uno de **larga duración**, andá a **Herramientas → Access Token Debugger**, pegá el token, y usá el botón **"Extend Access Token"** (o hacé el intercambio vía la API: `GET /oauth/access_token?grant_type=fb_exchange_token&client_id=TU_APP_ID&client_secret=TU_APP_SECRET&fb_exchange_token=TU_TOKEN_DE_USUARIO`). Esto te da un token de usuario de ~60 días.
4. Con ese token de usuario ya extendido, llamá a `GET /me/accounts?access_token=TU_TOKEN_DE_USUARIO_EXTENDIDO` (podés hacerlo directo en el Graph API Explorer). En la respuesta vas a ver tu Página listada, con su propio `access_token` — **ese es el `FB_PAGE_ACCESS_TOKEN`**.

En la práctica, un token de Página obtenido así **no suele vencer** mientras
no cambies tu contraseña de Facebook ni le quites permisos a la app — a
diferencia del token de Instagram, que sí vence siempre a los 60 días. De
todas formas, como es la primera vez que este bot lo usa en producción,
convendría que en unas semanas confirmemos que las publicaciones en Facebook
siguen saliendo bien, por si en la práctica se comporta distinto a lo
documentado.

---

## 5. Cargar las credenciales en GitHub (Secrets)

En tu repositorio nuevo: **Settings → Secrets and variables → Actions → New
repository secret**. Cargá estos 4:

| Nombre                  | Valor                                     |
|--------------------------|--------------------------------------------|
| `IG_USER_ID`             | El ID de tu cuenta de Instagram             |
| `IG_ACCESS_TOKEN`        | El token de larga duración de Instagram     |
| `FB_PAGE_ID`             | El ID de tu Página de Facebook              |
| `FB_PAGE_ACCESS_TOKEN`   | El token de acceso de la Página (paso 4.3)  |

---

## 6. Probar que funciona

1. En GitHub, pestaña **Actions** → workflow **"Publicar videos (Instagram + Facebook)"**.
2. **Run workflow**, elegí `fase1`, ejecutá. Revisá el log: debería subir el Trial Reel a Instagram.
3. Para probar Facebook sin esperar 24hs, corré de nuevo **Run workflow** eligiendo `fase2` (fuerza la publicación inmediata de lo que esté esperando, sin respetar el plazo — solo para pruebas).
4. Revisá tu Instagram y tu Página de Facebook para confirmar que se publicó todo bien.

**Sobre la primera prueba de Facebook en particular:** como es la primera vez
que se usa esta integración, es posible que el paso de verificación del
estado del video (`_wait_until_ready` en `facebook_publish.py`) no reconozca
perfectamente el valor exacto que devuelve Facebook una vez que el Reel ya
está publicado (la documentación de Meta no es muy clara en ese punto
específico). Si la corrida de prueba se queda esperando más de lo normal o
falla ahí, mandame el log completo de esa parte y lo ajustamos con el dato
real — está pensado para eso desde el diseño.

Una vez que probaste que anda, dejalo tranquilo: corre solo en los mismos 4
horarios diarios, en modo `ciclo`.

---

## 7. Agregar más videos después

Igual que el otro bot: subís el archivo a `videos/`, agregás su entrada en
`config/queue.json` con `"status": "pending"`, y hacés commit.

---

## Límites a tener en cuenta

- **Instagram**: hasta 100 publicaciones por API cada 24 horas.
- **Facebook Reels**: hasta 30 publicaciones por API cada 24 horas (documentado por Meta) — muy por encima de las 4 diarias de este bot.
- **GitHub Actions**: igual que el otro bot, muy por debajo del límite gratuito mensual.
- **Contenido repetido en Instagram**: al publicar el mismo video dos veces (trial + normal), Instagram puede limitarle un poco el alcance a la segunda copia — no es un bloqueo. En Facebook esto no aplica porque cada video se publica ahí una sola vez.

---

## 8. Respaldo externo con cron-job.org (recomendado)

Igual que en el bot original: el cron nativo de GitHub Actions es "best
effort" y puede saltearse alguna corrida, así que conviene un segundo
disparador externo y gratuito. Repetí exactamente los pasos 8.1 a 8.4 de la
guía del bot original, con dos diferencias:

- El **Personal access token** de GitHub tiene que darle acceso a ESTE
  repositorio nuevo (no al original) en el paso "Repository access".
- La **URL** de cada cronjob en cron-job.org apunta a este repo:
  `https://api.github.com/repos/TU_USUARIO/ig-fb-repost-bot/actions/workflows/publish.yml/dispatches`
  (cambiá `TU_USUARIO` y el nombre del repo por los reales).

El resto (los 4 horarios en UTC, el body `{"ref": "main", "inputs": {"fase": "ciclo"}}`, el mecanismo de "Reservar turno" que evita duplicados si los dos disparadores coinciden) funciona exactamente igual que en el bot original.
