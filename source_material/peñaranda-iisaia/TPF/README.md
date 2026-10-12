# Rules Companion 40k

Asistente de reglas de Warhammer 40.000 (11ª edición). Un agente navega las
reglas de Wahapedia siguiendo su índice: tiene el índice de core rules en el
contexto, abre el índice de un codex cuando la pregunta lo necesita y lee solo
las reglas que hacen falta. Generación con un modelo de Azure AI Foundry.

Tiene dos modos:

- **Aclaración** — chat para preguntar cómo funciona una regla
  (*"¿cómo hago para hacer una carga?"*). Los seguimientos (*"¿y si falla?"*)
  mantienen el contexto de la pregunta anterior.
- **Arbitraje** — se cargan la situación y la postura de cada jugador, y el
  modelo dicta un veredicto citando las reglas.

En los dos se puede indicar el ejército (codex y destacamento) o, mejor,
cargar la propia lista de New Recruit (`.rosz`, una por usuario): el agente
sabe entonces qué unidades, equipo, mejoras y destacamentos tenés, y lee sus
datasheets directamente. Cada
afirmación de reglas se cita con un enlace a la regla en Wahapedia, y la app
muestra qué consultó el agente y el texto de cada regla.

## Cómo correrlo

```bash
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt

# credenciales (.env, no se commitea):
#   azure_foundry_api_key=...
#   azure_foundry_url=https://<recurso>.services.ai.azure.com/openai/v1/responses
#   azure_foundry_model=gpt-5.6-luna          (opcional)
#   azure_foundry_reasoning_effort=medium     (opcional)

.venv/Scripts/python.exe -m wahapedia sync    # baja las reglas (una vez)
.venv/Scripts/streamlit.exe run app.py
```

El texto de las reglas no está en el repo: `sync` lo descarga de Wahapedia a
`data/wahapedia/`. La primera corrida tarda ~30 min (son ~270 datasheets, con
una pausa entre requests); después usa la cache y regenera todo en minutos.
`sync --refresh` vuelve a bajar todo para tomar cambios de reglas.

### Autenticación (Auth0, plan Free)

La app exige ingresar. Usa el login nativo de Streamlit (`st.login`, OpenID
Connect) contra Auth0:

1. En [manage.auth0.com](https://manage.auth0.com): *Applications → Create
   Application → Regular Web Applications*.
2. En *Settings*: *Allowed Callback URLs* = `http://localhost:8501/oauth2callback`
   y *Allowed Logout URLs* = `http://localhost:8501`. Guardar.
3. Copiar `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` (no se
   commitea) y completar `client_id`, `client_secret`, el dominio en
   `server_metadata_url` y un `cookie_secret` aleatorio.
4. Opcional: en *Authentication → Social* habilitar Google u otros
   proveedores; por defecto Auth0 ofrece usuario y contraseña.

### Base de datos

SQLite en `data/app.db` (no se versiona); se crea sola al arrancar la app.
Guarda el perfil de cada usuario (claims de Auth0) y cada pregunta con las
llamadas al modelo que hizo el agente, sus tokens y la metadata del modelo.
Las respuestas no se guardan. Esquema en `userdb.py`; para consultar el uso:

```sql
SELECT u.email, SUM(x.input_tokens), SUM(x.output_tokens)
FROM interaction_usage x JOIN users u ON u.id = x.user_id GROUP BY u.id;
```

### Panel de admin

App aparte, solo para la máquina local, con acceso de solo lectura a la base:

```bash
.venv/Scripts/python.exe -m streamlit run admin.py --server.port 8502 --server.address 127.0.0.1
```

El primer ingreso es con credenciales temporales (las de `.env`, o
`4dmin` / `pa$$temporal` si no hay) y el panel obliga a definir unas propias,
que quedan hasheadas (PBKDF2) en `data/admin_credentials.json`. Tras 5
intentos fallidos el panel se bloquea 15 minutos. Muestra un dashboard del mes (usuarios activos,
preguntas, costo, costo promedio por usuario, tokens por pregunta, costo
acumulado con proyección a fin de mes) y las tablas de interacciones (con el
detalle de llamadas al modelo de cada una), usuarios y llamadas. Los precios
por millón de tokens salen de `price_*_per_1m` en `.env` y se pueden ajustar
en el panel.

## Despliegue

`Dockerfile` arma una imagen con las dos apps detrás de Caddy, en un solo
puerto: la app en `/` y el panel en `/admin`. La guía paso a paso (Fly.io,
dominio propio, secretos, Auth0) está en [DEPLOY.md](DEPLOY.md).

## Arquitectura

```
app.py                front de Streamlit (los dos modos)
ui.py                 retoques de estilo que el tema no cubre
.streamlit/           tema (paleta, tipografía, radio 0) y secrets de Auth0
auth.py               pantalla de ingreso y sincronización del perfil
userdb.py             SQLite: usuarios, conversaciones, interacciones, llamadas
armylist.py           listas de New Recruit (.rosz): lectura segura, vínculo con el almacén, texto para el agente
admin.py              panel de admin (app aparte): datos guardados y costos
admin_auth.py         credenciales del panel: temporales -> propias (hash PBKDF2)
env.py                variables de entorno en minúsculas o mayúsculas

Dockerfile, fly.toml  imagen y despliegue en Fly.io (ver DEPLOY.md)
docker/entrypoint.sh  arranque: volumen, secretos, las dos apps y Caddy
docker/Caddyfile      ruteo / -> app, /admin -> panel
docker/write_secrets.py  genera secrets.toml de Auth0 desde el entorno

agent/engine.py       bucle del agente: herramientas hasta poder responder
agent/tools.py        get_rules, get_codex_index, search_rules
agent/prompts.py      instrucciones (con el índice de core) y plantilla de cada modo
agent/llm.py          cliente de /openai/v1/responses: tools + streaming

wahapedia/fetch.py    descarga con cache en disco y pausa entre requests
wahapedia/html2md.py  HTML -> texto, partido por ancla, con enlaces y diagramas
wahapedia/parse.py    índice "Contents" -> jerarquía; core, codex y datasheets
wahapedia/store.py    references, guardado con diff, índice y consultas
```

Datos en `data/wahapedia/`:

```
core.json, codices/<codex>.json   reglas completas (no se versionan)
index/core.md, index/<codex>.md   índice compacto para el contexto del agente
index/*.json                      el mismo índice como lista de RuleSummary
raw/                              cache del HTML (no se versiona)
```

Flujo de una consulta: el modelo recibe las instrucciones con el índice de
core y la pregunta; pide reglas con `get_rules` (varias por llamada), abre el
índice de un codex con `get_codex_index` si la pregunta nombra unidades,
destacamentos o estratagemas, y sigue las `references` de cada regla cuando
el texto depende de otra. Cuando no pide más herramientas, la respuesta llega
en streaming.

## Decisiones de implementación

**Retrieval agéntico en lugar de RAG por chunks.** El MVP partía el PDF en
chunks y los recuperaba con BM25; solo andaba bien trayendo muchos chunks.
Las reglas de 40k ya vienen organizadas en un índice y se citan entre sí, así
que el agente navega esa estructura: elige por el índice y sigue las
referencias, como haría un jugador con el reglamento.

**Wahapedia en lugar del PDF.** Trae core rules, codex, destacamentos,
estratagemas y datasheets con la misma estructura de anclas y enlaces, y se
actualiza cuando cambian las reglas (errata y FAQ incluidas en cada regla).
El scraping es offline (`sync`); en una consulta no se le pide nada al sitio.
Ver la sección 4 de `SSD.md` para el detalle del parser.

**Herramientas pocas y gruesas.** `get_rules` acepta varias reglas por
llamada, porque cada vuelta del modelo cuesta segundos. Si el modelo arma mal
un href de core (por ejemplo con el número del reglamento), se rescata por
número o por nombre en vez de devolver error.

**Estado del lado del proveedor.** Cada vuelta usa `previous_response_id`: solo
se manda la salida de las herramientas, el proveedor mantiene la
conversación y su cache. Lo mismo encadena los seguimientos del chat.

**Razonamiento medio.** Con varias vueltas por consulta, `high` se vuelve lento;
`medium` responde en 10–20 s. Configurable con `azure_foundry_reasoning_effort`.

**Anclaje a las reglas leídas.** El prompt prohíbe usar conocimiento previo del
juego (mezcla ediciones), obliga a citar con enlace solo lo que se leyó y fija
la precedencia misión > codex > core.

**Auth0 vía `st.login`.** Streamlit implementa el flujo OIDC completo (redirección,
validación del ID token, cookie firmada), así que no hay código de OAuth
propio. Auth0 aporta usuario/contraseña y logins sociales; el plan Free
alcanza para un proyecto de este tamaño.

**SQLite, una fila por llamada al modelo.** Una pregunta dispara varias llamadas
(una por vuelta de herramientas), cada una con sus tokens: se guardan todas en
`model_calls` y la vista `interaction_usage` las suma por pregunta. Así se puede
medir costo por usuario y cuánto ahorra la cache del proveedor.

## Estilo visual

La interfaz sigue el sistema de diseño de Lamborghini.com: escenario oscuro
monocromo (`#202020` / `#181818` / blanco) con un único acento Giallo Vivo
`#ffc000`, esquinas rectas (radio 0), sin sombras —la separación es por
contraste de superficie y filete de 1px—, títulos en mayúsculas con tracking
0.0230em y jerarquía por escala de tipo, nunca por peso.

Casi todo entra en `.streamlit/config.toml`. `ui.py` agrega solo lo que el tema
no puede expresar: mayúsculas, tracking y la tinta negra del botón Giallo
(el blanco que pone Streamlit no contrasta sobre el amarillo). LamboType es
exclusiva de la marca, así que se usa **Archivo** como sustituto libre.

## Limitaciones conocidas

- Solo core rules y los codex de Space Marines y Orks; sin reglas de misión.
- Una consulta lleva varias vueltas del modelo: 10–20 s, más que el MVP.
- 3 diagramas de core no tienen descripción en Wahapedia; el agente no los ve.
- Sin evaluación cuantitativa todavía (conjunto de preguntas con respuesta
  esperada).
- "Salir" cierra la sesión de la app, no la de Auth0: el próximo ingreso puede
  ser automático. Para pedir siempre la pantalla de Auth0, ver `client_kwargs`
  en `secrets.toml.example`.
- Publicidad (AdSense) sin implementar: el perfil ya tiene los campos de
  consentimiento (`ads_consent`), pero falta el aviso de privacidad y la
  pantalla de consentimiento.
