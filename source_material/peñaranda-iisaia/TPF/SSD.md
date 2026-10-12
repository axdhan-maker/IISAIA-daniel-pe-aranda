# SSD — Rules Companion 40k

**Documento de especificación de software** · v2.3 · 2026-10-12

Cambios respecto de la v1.0 (MVP): el RAG sobre el PDF se reemplaza por un
agente que navega las reglas de Wahapedia siguiendo su índice, y el alcance
se amplía a codex, destacamentos, estratagemas y datasheets. El diseño sigue
el contrato del TP2 (`openapi.yaml`). La v2.1 agrega autenticación con Auth0 y
una base de datos de usuarios e interacciones; la v2.2, el panel de admin y
el despliegue en contenedor; la v2.3, la lista de ejército del usuario
(`.rosz` de New Recruit).

---

## 1. Propósito y alcance

Asistente de consulta sobre las reglas de Warhammer 40.000 (11ª edición).
Responde preguntas y arbitra disputas fundándose en las reglas publicadas en
Wahapedia, citando cada regla con un enlace a su fuente.

**Dentro del alcance:** core rules y rules appendix; codex de Space Marines y
Orks (army rules, destacamentos con sus reglas, mejoras y estratagemas, y
datasheets); dos modos de consulta; interfaz web en local con usuarios
autenticados; registro de preguntas y consumo del modelo por usuario.

**Fuera del alcance:** reglas de misión; otros codex; Boarding Actions;
memoria entre sesiones (resúmenes por usuario del TP2); publicidad (el perfil
queda preparado para el consentimiento); alta disponibilidad (una sola
instancia con SQLite).

## 2. Requerimientos

### Funcionales

| ID | Requerimiento |
|----|---------------|
| RF-1 | **Modo aclaración**: el usuario pregunta cómo funciona una regla y recibe una explicación con pasos y excepciones. |
| RF-2 | **Modo arbitraje**: el usuario carga la situación y la postura de dos jugadores; el sistema emite un veredicto sobre quién tiene razón. |
| RF-3 | Toda afirmación de reglas se cita con un enlace a la regla en Wahapedia, con su nombre y numeración. |
| RF-4 | La interfaz muestra qué consultó el agente y el texto de cada regla usada, con sus diagramas. |
| RF-5 | El sistema responde en el idioma de la consulta, aunque las reglas estén en inglés. |
| RF-6 | El sistema declara explícitamente cuándo las reglas leídas no alcanzan para responder. |
| RF-7 | El usuario puede indicar su ejército (codex y destacamento); en arbitraje, el de cada jugador. |
| RF-8 | En modo aclaración, las preguntas de seguimiento conservan el contexto de las anteriores. |
| RF-9 | Ante un conflicto entre reglas se aplica la precedencia misión > codex > core. |
| RF-10 | El usuario debe ingresar con Auth0 para usar la app; puede salir desde la barra lateral. |
| RF-11 | Se registra cada pregunta del usuario (no la respuesta) con el ejército elegido, la latencia, las reglas consultadas y, por cada llamada al modelo, tokens de entrada (y cacheados), de salida (y de razonamiento) y la metadata del modelo. |
| RF-13 | El usuario puede cargar su lista de ejército exportada de New Recruit (`.rosz`, 11ª edición); una sola por usuario: una nueva reemplaza a la anterior (con aviso) y se puede borrar. La lista se usa en aclaración y como ejército del jugador 1 en arbitraje. |
| RF-12 | Un panel de admin, separado de la app de jugadores y con credenciales propias, muestra usuarios, preguntas y llamadas al modelo, el costo del mes, el costo promedio por usuario y la proyección a fin de mes. |

### No funcionales

| ID | Requerimiento |
|----|---------------|
| RNF-1 | Respuesta completa en ~10–20 s, con el progreso del agente visible y el texto en streaming. |
| RNF-2 | Sin servidores propios: las reglas viven en JSON locales y los usuarios en SQLite. Servicios externos: el endpoint del modelo y Auth0. |
| RNF-3 | Credenciales fuera del código, en `.env` y `.streamlit/secrets.toml`, excluidos del control de versiones. |
| RNF-4 | Trazabilidad: el usuario siempre puede auditar de qué regla salió cada afirmación. |
| RNF-5 | Reproducible con `requirements.txt` sobre Python 3.10. |
| RNF-6 | El texto de las reglas no se versiona; se regenera con `python -m wahapedia sync`. |
| RNF-7 | El scraping respeta el sitio: cache local y 1,5 s entre requests. |
| RNF-8 | Una falla al consultar el modelo también se registra, con las llamadas que llegaron a hacerse. |
| RNF-9 | El panel de admin abre la base en solo lectura y guarda la contraseña hasheada (PBKDF2-SHA256), no en texto plano. En local escucha solo en `127.0.0.1`. |
| RNF-10 | Desplegable como una imagen Docker en cualquier servicio con disco persistente, dominio propio y HTTPS, a bajo costo. |
| RNF-12 | La carga de listas no confía en el archivo: máximo 1 MB comprimido y 5 MB descomprimido, un único `.ros`, XML leído con `defusedxml` (sin entidades ni DTD) y solo el sistema "Warhammer 40,000 11th Edition". |
| RNF-11 | Todo despliegue nuevo arranca con credenciales de admin conocidas (`4dmin` / `pa$$temporal`) y obliga a reemplazarlas en el primer ingreso; las nuevas persisten en el disco. Bloqueo global de 15 min tras 5 intentos fallidos. |

## 3. Arquitectura

```
                 ┌──────────────────────────────┐        ┌──────────────────────┐
   navegador ──► │ app.py  (Streamlit)          │ ◄────► │ Auth0 (OIDC)         │
                 │  auth.py: st.login           │        └──────────────────────┘
                 │  modo aclaración / arbitraje │ ─────► data/app.db (userdb.py)
                 └───────────┬──────────────────┘
                             │
                 ┌───────────▼──────────────────┐        ┌──────────────────────┐
                 │ agent/engine.py              │ ─────► │ Azure AI Foundry     │
                 │ bucle: herramientas → texto  │ ◄───── │ gpt-5.6-luna         │
                 └───────────┬──────────────────┘ tools  └──────────────────────┘
                             │ get_rules / get_codex_index / search_rules
                 ┌───────────▼──────────────────┐
                 │ wahapedia/store.py           │  consultas del openapi
                 └───────────┬──────────────────┘
                             │
            ┌────────────────▼─────────────────┐
            │ data/wahapedia/                  │
            │ core.json, codices/*.json, index/│
            └────────────────▲─────────────────┘
                             │
            ┌────────────────┴─────────────────┐
            │ python -m wahapedia sync         │  offline, a pedido
            │ fetch → html2md → parse → store  │ ◄──── wahapedia.ru/wh40k11ed
            └──────────────────────────────────┘
```

| Componente | Responsabilidad |
|------------|-----------------|
| `wahapedia/fetch.py` | Descarga con cache en `data/wahapedia/raw/` y pausa entre requests. |
| `wahapedia/html2md.py` | HTML → texto Markdown, un segmento por ancla `<a name>`; junta enlaces (directos y de tooltips) y diagramas. Descarta publicidad y ambientación; conserva FAQ y errata. |
| `wahapedia/parse.py` | Jerarquía a partir del recuadro "Contents"; reglas de core, codex y datasheets. |
| `wahapedia/store.py` | Resuelve `references`, guarda con diff, genera el índice y expone las operaciones del openapi. |
| `agent/tools.py` | Herramientas del modelo sobre `store.py`; registra las reglas consultadas. |
| `agent/prompts.py` | Instrucciones (con el índice de core) y plantilla de cada modo. |
| `agent/engine.py` | Bucle de herramientas, encadenado con `previous_response_id`. |
| `agent/llm.py` | Cliente de `/openai/v1/responses` con tools, streaming y reintentos de red. |
| `auth.py` | Pantalla de ingreso (`st.login`) y sincronización del perfil una vez por sesión. |
| `userdb.py` | Esquema SQLite y escritura de usuarios, conversaciones, interacciones y llamadas al modelo. |
| `armylist.py` | Lee el `.rosz` y lo traduce al almacén: catálogo → codex, destacamentos (varios, por Detachment Points) → ids, unidades → datasheet; detecta warlord y mejoras (cruzando con las mejoras de sus destacamentos); arma el texto que recibe el agente. |
| `admin.py` / `admin_auth.py` | Panel de admin (app aparte, puerto 8502) y sus credenciales: temporales → propias, con bloqueo ante fuerza bruta. |
| `Dockerfile` / `docker/` | Imagen: Caddy en `$PORT` rutea `/admin` al panel y el resto a la app; el arranque prepara el volumen `/data`, genera `secrets.toml` desde el entorno y supervisa los tres procesos. |
| `app.py` / `ui.py` | Interfaz y estilo. |

**Despliegue.** Un contenedor (`Dockerfile`) con disco persistente en
`/data` (base, credenciales de admin, secreto de cookie). Las reglas viajan
en la imagen si están sincronizadas al construir; si no, se descargan al disco
en el primer arranque. Configuración por variables de entorno (ver
`DEPLOY.md`). Plataforma de referencia: Fly.io, región `iad`, junto a Azure
East US, porque cada consulta hace varias vueltas al modelo.

## 4. Diseño de datos

**Fuentes (11ª edición, `wahapedia.ru/wh40k11ed/`).**

| Capa | Fuente | Contenido |
|------|--------|-----------|
| `core` | core rules + rules appendix | 301 reglas, 39 diagramas (36 con descripción de Wahapedia) |
| `codex` | Space Marines | 12 army rules, 35 destacamentos (35 reglas, 93 mejoras, 142 estratagemas), 191 datasheets |
| `codex` | Orks | 6 army rules, 15 destacamentos (15 reglas, 38 mejoras, 40 estratagemas), 67 datasheets |

**Regla.** Sigue el schema `Rule` del openapi:

```json
{"id": "2-charge-step", "layer": "core", "kind": "core_rule", "name": "2. Charge Step",
 "number": "11.02", "section": ["THE BATTLE ROUND", "Charge Phase", "2. Charge Step"],
 "href": "/core/rules/2-charge-step", "text": "...",
 "references": [{"layer": "core", "rule_id": "engagement", "name": "Engagement", "href": "/core/rules/engagement"}],
 "source_url": "https://wahapedia.ru/wh40k11ed/the-rules/core-rules/#2.-Charge-Step",
 "anchors": ["2.-Charge-Step"], "figures": [], "scraped_at": "2026-10-11T..."}
```

`number` es la numeración del reglamento (para citar). `anchors` son las anclas
de Wahapedia que resuelven a la regla. Las core rules traen `figures` (URL de
la imagen, título y descripción). Las reglas de codex traen `codex_id` y
`detachment_id`; sus ids son únicos dentro del destacamento, porque la misma
estratagema puede repetirse entre destacamentos.

**Generación (`sync`).** Cada ancla `<a name>` del HTML abre una regla. La
jerarquía sale de los niveles de sangría del recuadro "Contents"; las anclas
que no figuran ahí cuelgan de la última entrada que las precede. Las mejoras no
tienen ancla propia: se insertan antes de separarlas. Los enlaces del texto
(directos o vía tooltip) se resuelven a `references` contra todas las reglas;
un enlace a un encabezado sin texto propio (p. ej. "Attached Units") cae en su
primera regla. Cada corrida informa reglas agregadas, modificadas y quitadas.

**Base de datos (`data/app.db`, SQLite).**

```
users 1 ── N conversations 1 ── N interactions 1 ── N model_calls
  └──────────────── 1 ── N ─────────┘ (user_id también en interactions)
```

| Tabla | Clave | Contenido |
|-------|-------|-----------|
| `users` | `id`; `auth0_sub` único | Claims de Auth0 (`sub`, email y verificación, nombre, nickname, foto, locale), proveedor de identidad (prefijo del `sub`), consentimiento de anuncios (`ads_consent`, `ads_consent_at`), alta, última visita y cantidad de sesiones. |
| `conversations` | `id` (uuid) → `users` | Un chat de aclaración (hasta "Limpiar conversación") o un arbitraje; `mode` = `question` / `dispute`, como en el openapi. |
| `interactions` | `id` → `conversations`, `users` | Prompt, ejército (JSON), estado y error, latencia, reglas consultadas. |
| `model_calls` | `id` → `interactions` | Una fila por vuelta del agente: proveedor, modelo, esfuerzo de razonamiento, `tool_choice`, herramientas pedidas, `response_id` y `previous_response_id`, tokens de entrada, cacheados, de salida y de razonamiento, latencia. |

`army_lists` (clave `user_id` → `users`, una por usuario): nombre, archivo,
codex, facción, destacamentos (JSON), puntos, la lista interpretada (JSON) y el
`.rosz` original (BLOB), para volver a interpretarlo si cambia el parser.

La vista `interaction_usage` suma los tokens por interacción. El panel de admin
calcula el costo como (entrada − cacheados) × precio de entrada + cacheados ×
precio cacheado + salida × precio de salida (los tokens de razonamiento ya
están en los de salida), con precios por millón de tokens de `.env`. La
proyección a fin de mes es lo gastado más el costo por usuario activo y por día
de los últimos 7 días × usuarios activos del mes × días restantes. Las claves
foráneas están activas y borran en cascada (borrar un usuario borra su
historial).

**Índice.** `index/core.md` (~20 KB) es el árbol que va siempre en las
instrucciones del agente; `index/<codex>.md` se entrega cuando el agente lo
pide. Los mismos índices están en JSON como lista de `RuleSummary`.

## 5. Interfaces

**Herramientas del modelo.**

| Herramienta | Entrada | Salida |
|-------------|---------|--------|
| `get_rules` | `hrefs: string[]` | Por cada regla: nombre, número, capa, `source_url`, texto, descripciones de diagramas y `references`. |
| `get_codex_index` | `codex_id` (enum) | Índice del codex: army rules, destacamentos con sus reglas, mejoras y estratagemas, datasheets. |
| `search_rules` | `query` | Hasta 8 reglas por coincidencia en nombre y texto (respaldo). |

**Modelo (salida).** `POST {azure_foundry_url}` con `Authorization: Bearer`,
cuerpo `{model, instructions, input, tools, tool_choice, reasoning:{effort},
previous_response_id, stream}`; respuesta SSE: se consumen
`response.output_text.delta` y `response.completed` (que trae las llamadas a
herramientas). Tras 6 vueltas con herramientas se fuerza la respuesta con
`tool_choice: "none"`. Configuración por `.env`: `azure_foundry_api_key`,
`azure_foundry_url`, `azure_foundry_model` (def. `gpt-5.6-luna`),
`azure_foundry_reasoning_effort` (def. `medium`).

**Identidad.** OIDC contra Auth0 vía `st.login`: Streamlit redirige a Auth0,
valida el ID token y guarda la identidad en una cookie firmada. Configuración
en `.streamlit/secrets.toml` (`[auth]`: `redirect_uri`, `cookie_secret`,
`client_id`, `client_secret`, `server_metadata_url`).

**Usuario.** Streamlit, detrás de la pantalla de ingreso. Modo aclaración: chat con seguimiento y ejército
opcional en la barra lateral. Modo arbitraje: ejército de cada jugador y
formulario de tres campos (situación, postura 1, postura 2). En ambos, una
línea de tiempo muestra cada consulta del agente mientras ocurre, el texto
llega en streaming y debajo se listan las fuentes con su texto y diagramas.

## 6. Decisiones de diseño

| Decisión | Motivo | Alternativa descartada |
|----------|--------|------------------------|
| Retrieval agéntico por índice | Las reglas ya vienen indexadas y se citan entre sí; el BM25 del MVP solo andaba trayendo muchos chunks. | RAG por chunks (BM25 o embeddings) |
| Wahapedia en lugar del PDF | Cubre codex y datasheets con la misma estructura, se actualiza con las reglas y trae errata/FAQ. | PDF oficial |
| Una regla por ancla de Wahapedia | Es la granularidad a la que el sitio enlaza las reglas: las referencias resuelven sin heurísticas. | Una regla por entrada del índice (pierde sub-reglas) |
| Índice de core siempre en contexto; codex a pedido | El core aplica a casi toda pregunta; los codex solo si se nombran (~20 KB contra ~30 KB más). | Todos los índices siempre |
| `get_rules` acepta varias reglas | Cada vuelta del modelo cuesta segundos. | Una regla por llamada |
| `previous_response_id` | El proveedor guarda la conversación y su cache; habilita los seguimientos del chat. | Reenviar todo el historial |
| `reasoning.effort = "medium"` | Con varias vueltas, `high` alarga la respuesta sin mejora visible. | `high` (v1.0) |
| Datasheets sin la lista de estratagemas aplicables | Es derivada y repite el codex entero. | Página completa |
| Texto de reglas fuera del repo | Es contenido de GW y se regenera con `sync`; se versiona solo el índice. | Versionar todo |
| Prompt que prohíbe conocimiento previo | El modelo conoce 40k de su entrenamiento y mezclaría ediciones. | Prompt abierto |
| Auth0 vía `st.login` | Sugerido en clase; plan Free (25.000 usuarios activos/mes) y OIDC estándar, que Streamlit soporta sin código de OAuth propio. | OAuth a mano; password compartida |
| SQLite | Una base de un archivo, sin servidor, con la librería estándar; alcanza para un usuario local o pocos concurrentes. | PostgreSQL / servicio gestionado |
| Una fila por llamada al modelo | Una pregunta son varias llamadas: guardar cada una permite medir costo y aprovechamiento de la cache. | Solo totales por pregunta |
| Se guardan prompts, no respuestas | Pedido explícito: interesa qué preguntan y cuánto cuesta. | Guardar la conversación completa |
| Consentimiento de anuncios en el perfil | Los anuncios personalizados requieren consentimiento; AdSense no recibe datos del perfil. | Sin registro de consentimiento |
| Panel de admin como app aparte | No comparte sesión ni login con los jugadores y se puede dejar solo en localhost. | Página oculta dentro de la app |
| Credenciales del admin en `.env` con hash | Pedido: credenciales locales simples; el hash evita exponer la contraseña si se filtra el archivo. | Usuario admin en Auth0 (roles) |
| Proyección por usuario activo | Escala con la cantidad de usuarios, que es lo que más mueve el costo. | Extrapolar el total diario |
| Un contenedor con Caddy y dos procesos de Streamlit | Las dos apps quedan tal cual y salen por un único puerto, que es lo que dan las plataformas baratas. | Dos servicios separados; fusionar el panel en la app |
| Fly.io | Construye la imagen en sus servidores (no hace falta Docker local) y con la carpeta local, así las reglas viajan sin estar en el repo; disco persistente y certificados de dominio propio incluidos; ~US$ 6/mes. | Railway / Render (sin las reglas en la imagen); VPS (más mantenimiento) |
| Credenciales de admin temporales y cambio obligatorio | Cualquier despliegue nuevo es accesible con una clave conocida y deja de serlo al primer ingreso. | Clave fija por variable de entorno |
| Lista como texto con hrefs en el prompt | El agente sabe qué unidades y equipo hay sin una herramienta más, y pide cada datasheet por su href sin buscarla. | Herramienta `get_army_list` |
| Una lista por usuario (clave primaria `user_id`) | Pedido de producto; la base lo garantiza, no solo la interfaz. | Varias listas con una activa |
| Mejoras detectadas por dos vías | New Recruit las marca con el grupo `Enhancements::<destacamento>`; además se cruzan por nombre con las mejoras de esos destacamentos en el almacén, por si otra exportación no trae el grupo. | Solo el grupo del XML |
| Historial de chat solo en sesión | La conversación con el modelo vive en el proveedor (`previous_response_id`). | Reconstruirla desde la base |

## 7. Verificación

| Qué | Cómo |
|-----|------|
| Scraping | Conteos por fuente y diff por corrida; inspección de reglas, references y diagramas de referencia (p. ej. Engagement, Armour of Contempt). Enlaces sin resolver: solo los de otras facciones y anclas rotas de Wahapedia. |
| Datasheets | Comparación de perfiles, armas, habilidades y LEADER contra la página en casos distintos (Intercessor Squad, Captain, Repulsor, Warboss). |
| Agente | Consultas reales con el modelo: unidad + core (Intercessors en engagement), facción + destacamento (Waaagh! con War Horde). Se revisa qué reglas consulta y que las citas correspondan. |
| Flujo punta a punta | `streamlit.testing.v1.AppTest`: aclaración con ejército, seguimiento y arbitraje con dos ejércitos, contra el modelo real. |
| Trazabilidad | Las fuentes y los pasos se muestran en la interfaz: una cita infundada es visible. |
| Autenticación | `AppTest` en tres estados: sin `[auth]` (aviso de configuración), sin login (pantalla de ingreso, sin chat) y logueado (claims simulados de Auth0). El login real contra Auth0 se prueba a mano con el tenant configurado. |
| Panel de admin | `AppTest`: clave incorrecta (rechazo y conteo de intentos), clave correcta, las cuatro pestañas y las métricas sobre la base real. |
| Contenedor | Sin Docker local: el arranque real (`docker/entrypoint.sh`) corrido sobre una copia filtrada por `.dockerignore`, con Caddy: rutas `/`, `/admin` (redirección), health de las dos apps, WebSocket (101) por el proxy, `secrets.toml` generado desde el entorno y archivos en el volumen. El `docker build` queda por verificar en el primer `fly deploy`. |
| Credenciales de admin | `AppTest`: temporales → formulario de cambio, validaciones, guardado, rechazo de las temporales después, ingreso con las nuevas; bloqueo global tras 5 fallos; credenciales de fábrica sin configuración. |
| Listas | Las dos muestras de New Recruit (Space Marines con dos destacamentos, Orkos): facción, destacamentos, warlord, mejoras (4, incluida una de tipo upgrade sobre una unidad), composición, equipo y vínculo de todas las unidades con su datasheet. Rechazo de archivos inválidos: no ZIP, sin `.ros`, XML roto, otra edición, *billion laughs* y *zip bomb* (48 KB → 50 MB). `AppTest` con consulta real sobre "mis Boyz", registro en la base, reemplazo, borrado y uso en arbitraje. |
| Base de datos | Prueba directa de `userdb` (upsert, claves foráneas, vista) y `AppTest` logueado con consultas reales: se verifican las filas de las cuatro tablas. |

## 8. Limitaciones y trabajo futuro

- Sin reglas de misión (capa `mission` del openapi) ni otros codex: agregar un
  codex es `sync --codex <id>`.
- Memoria por usuario del TP2 (resúmenes de conversación) sin implementar; ya
  hay `users` y `conversations` donde colgarla.
- "Salir" cierra la sesión de la app, no la de Auth0 (`client_kwargs` con
  `prompt = "login"` fuerza la pantalla de Auth0).
- Publicidad: falta aviso de privacidad, pantalla de consentimiento y la
  integración de AdSense, que no admite anuncios dentro de iframes de terceros:
  requiere una página propia alrededor de la app.
- 3 diagramas de core sin descripción en Wahapedia: falta generarla con un
  modelo de visión (`description_source: null`).
- Latencia de 10–20 s por las vueltas del agente.
- Sin evaluación cuantitativa: falta un conjunto de preguntas con respuesta
  esperada para medir aciertos y reglas consultadas.
