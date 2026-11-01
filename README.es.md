# video-factcheck

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![tests](https://github.com/vonavikon/video-factcheck/actions/workflows/tests.yml/badge.svg)](https://github.com/vonavikon/video-factcheck/actions/workflows/tests.yml)

[RU](README.md) · [EN](README.en.md) · [中文](README.zh.md) · **Español** · [Français](README.fr.md)

Una extensión de Chrome (MV3) que verifica las afirmaciones de videos de YouTube mientras los ves. Lee los subtítulos directamente de la página, el servidor extrae las afirmaciones verificables con su marca de tiempo, comprueba cada una (contra verificaciones humanas existentes, búsqueda web y artículos científicos) y muestra los veredictos «verdadero / falso / dudoso» en un panel junto al reproductor. Un clic en la marca de tiempo salta al momento del video donde se dijo la afirmación; cada veredicto lleva una fuente con cita textual.

«Dudoso» es un veredicto de pleno derecho, no un comodín: marca afirmaciones donde dos pasadas de búsqueda web discreparon o donde las fuentes no alcanzaron. La capa científica es deliberadamente prudente: un artículo solo mueve un veredicto si trata el tema directamente y es suficientemente reciente, y nunca dicta «falso»: como máximo rebaja «verdadero» a «dudoso».

![Cómo funciona: panel de verificación sobre YouTube, tarjetas de afirmaciones con veredictos y marcas de tiempo, un clic en la marca salta el video, cada veredicto lleva fuente con cita y peso](assets/concept.gif?v=f3eff95)
Versión en vídeo (16 s, sin sonido): [how-it-works.mp4](assets/how-it-works.mp4?v=f3eff95)

## Cómo funciona

```text
[cascada de subtítulos]   los subtítulos se leen de la página; yt-dlp en el servidor es el respaldo
        ↓
[extracción de afirmaciones]   hechos verificables con marcas de tiempo; las opiniones van a «no verificable»
        ↓
[verificación, tres capas en paralelo]
        ├─ ClaimReview: verificaciones humanas existentes (Google Fact Check Tools)
        ├─ sonar × 2: búsqueda web; pasadas en desacuerdo → «dudoso»
        └─ ciencia: Europe PMC → OpenAlex, adjudicación NLI sobre resúmenes
        ↓
[fusión del veredicto]    conflicto «verdadero vs ciencia-refuta» → «dudoso»
        ↓
[panel en YouTube]        tarjetas con marcas de tiempo, fuentes y peso de la fuente
```

- **Cascada de subtítulos.** Octubre de 2026: YouTube cerró el acceso directo a los subtítulos, así que la extensión prueba rutas en orden: un puente desde el mundo de la página (captionTracks del reproductor vivo), `timed_text`, el panel DOM «Transcripción», el endpoint `get_transcript` con las cookies de la página. Si todo falla, el servidor baja los subtítulos con yt-dlp.
- **Afirmaciones.** Un LLM etiqueta los segmentos de la transcripción: cita textual, categoría, significancia. Las opiniones, predicciones y la hipérbole van a «no verificable»; los duplicados se colapsan por hash normalizado.
- **ClaimReview.** Si la afirmación ya fue verificada por humanos (PolitiFact, Snopes, AFP, Provereno.media), se muestra su veredicto con la atribución al medio, sin llamar al LLM. Esas tarjetas llegan primero, antes de que termine la extracción.
- **sonar × 2.** Cada verificación corre dos pasadas por un modelo con búsqueda web incorporada; si las pasadas discrepan, el resultado es «dudoso». Una fuente solo se acepta con cita textual; las citas inventadas se filtran.
- **Capa científica.** Europe PMC (medicina/biología, sin clave) y OpenAlex (toda la ciencia). Un modelo barato adjudica la relación entre el conocimiento establecido y la afirmación sobre los 3 mejores resúmenes. Guardas de influencia: un artículo mueve el veredicto solo si trata el tema directamente, es de 2015 en adelante (o es una revisión/metaanálisis) y se respalda con cita textual.
- **Fusión.** «Verdadero» contradicho por la ciencia se rebaja a «dudoso» con confianza «baja» y una explicación fusionada. En la otra dirección, la ciencia nunca sube un veredicto.
- **Panel.** Un flujo de tarjetas con filtro por veredicto, un mapa de veredictos sobre la línea de tiempo del video, una escala de confianza y las fuentes con el peso resaltado («ciencia», «oficial»).

## Funciones

- Veredictos «verdadero / falso / dudoso» con marcas de tiempo y escala de confianza; un clic en la marca salta a ese momento del video
- Capa científica con guardas de pertinencia y frescura (Europe PMC → OpenAlex), adjudicada sobre resúmenes con cita textual obligatoria
- Peso de las fuentes resaltado («ciencia», «oficial») según un registro de confianza de dominios
- Interfaz RU/EN; el idioma de las explicaciones de los veredictos se configura aparte del idioma de la interfaz
- Historial de los últimos 50 videos verificados, en local en tu navegador
- Panel morfológico: se pliega en un círculo con insignia de «listo» y no estorba mientras corre la verificación

## Instalar desde el código fuente

Necesitas Chrome/Edge 111+ y Python 3.12+. La extensión no está en Chrome Web Store; solo instalación desde fuente. Todas las verificaciones pasan por tu propio servidor en `127.0.0.1:8765`, con tus propias claves de API.

### Servidor

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Linux/macOS: .venv/bin/pip
cd ..
cp .env.example .env
```

Rellena tus claves en `.env`:

- `VFC_LLM_KEY`: clave de un proveedor compatible con OpenAI (bothub por defecto: deepseek extrae afirmaciones y adjudica el NLI, sonar emite veredictos con búsqueda web de su lado). Obligatoria.
- `VFC_SERPER_KEY`: tu clave de búsqueda de Serper para el backend de búsqueda.
- `VFC_FACTCHECK_KEY`: clave de Google Fact Check Tools; sin ella la capa ClaimReview simplemente se omite.

Europe PMC y OpenAlex funcionan sin claves. Arranca el servidor:

```bash
cd backend
.venv/Scripts/python -m videofactcheck.cli serve --port 8765
```

Sin Chrome puedes verificar un video suelto desde la CLI: `.venv/Scripts/python -m videofactcheck.cli check "<url del video>"`.

### Extensión

1. Abre `chrome://extensions` y activa el «Modo de desarrollador».
2. «Cargar descomprimida» → la carpeta `extension` de este repositorio.
3. Abre cualquier video de YouTube: aparece el panel «Verificación» a la derecha. Pulsa «Verificar video».

Los subtítulos llegan en unos 10 segundos, las afirmaciones en 2-4 minutos para un video de 15 minutos; los veredictos van llegando según están listos, y no hace falta esperar: pliega el panel y la verificación sigue en segundo plano.

## Arquitectura

```text
extension/                    Chrome MV3
  content.js                  panel en YouTube: tarjetas, mapa de marcas de tiempo, plegado en círculo
  page-bridge.js              script en el mundo MAIN: captionTracks y videoDetails del reproductor vivo
  background.js               service worker: habla con el servidor
  options.html, account.html  ajustes (idioma) e historial de 50 videos en chrome.storage
backend/                      FastAPI + CLI
  videofactcheck/transcript.py       respaldo de subtítulos del servidor: yt-dlp, parser VTT con limpieza de subtítulos automáticos
  videofactcheck/claims.py           extracción de afirmaciones con marcas de tiempo
  videofactcheck/factcheck_db.py     ClaimReview: verificaciones humanas existentes
  videofactcheck/verdict.py          sonar × 2, escala de confianza, fusión
  videofactcheck/plausibility.py     capa científica: Europe PMC → OpenAlex, NLI con cita
  videofactcheck/trust.py            pesos de confianza de dominios (whitelist/blacklist)
  videofactcheck/store.py            SQLite: corridas, veredictos, transcripciones
  videofactcheck/server.py           API HTTP para la extensión (127.0.0.1:8765)
  videofactcheck/cli.py              `serve` y `check <url>`
  tests/                             72 tests, pytest
```

La extensión envía al servidor una transcripción leída de la página (las peticiones a YouTube salen desde la IP del usuario, no desde la del servidor) y recibe los veredictos a medida que se completan.

## Estado

Proyecto personal. Versión 0.9.1 (octubre de 2026), ejercitado en videos reales.

El proyecto creció por iteraciones con feedback de corridas reales: la cascada de subtítulos apareció cuando YouTube cerró el acceso directo en octubre de 2026; la cinta de ClaimReview (las verificaciones humanas llegan con los primeros lotes de extracción) y la estratificación de veredictos por línea de tiempo salieron de corridas largas sobre entrevistas de 40 minutos; el panel plegable salió de una queja: «el panel tapa la pantalla».

Limitaciones: los videos sin subtítulos se rechazan (la transcripción automática está planificada), los directos y Shorts no se soportan, una corrida emite como máximo 15 veredictos; el resto queda marcado «sin verificar».

## Licencia

MIT, ver [LICENSE](LICENSE).
