# Prompts — Proyecto final (Rules Companion 40k)

El registro de los prompts con los que se construyó esta versión de la app,
en orden, dentro de una sola conversación con Claude Code. Parte del MVP que
ya existía en la carpeta (RAG sobre el PDF de reglas, documentado en la v1.0
de `SSD.md`), cuyos prompts no forman parte de este registro, y del contrato
del TP2 (`../tp2/openapi.yaml`).

Cada entrada tiene el prompt textual y, debajo, lo que se hizo. Cuando el
asistente pidió una decisión con opciones, la respuesta elegida figura como
**Decisión**.

---

## 1 — Scraping de Wahapedia e índice de reglas

```
este repo es para una materia de la universidad, tengo un proyecto, crear un rules companion
para ayudarme a jugar 40k, hay un mvp empezado en la carpeta TPF, donde hay un archivo que
guia lo que hay @TPF/SSD.md sin embargo quiero mejoras, en el tp2 estuve explorando ideas,
se pueden ver en la carpeta que esta en @source_material/peñaranda-iisaia/tp2/openapi.yaml
el readme y los prompts te dicen que es lo que quiero hacer, lo primero es cambiar el RAG
sencillo implementado en scrapear wahapedia y descargar las reglas de: core rules, codex
space marines y codex orkos, de la edición 11 del juego, y luego crear un indice con el
indice que trae el sistema de reglas
```

**Qué se hizo:** paquete `wahapedia/` (descarga con cache, conversión HTML →
texto por ancla, jerarquía tomada del recuadro "Contents" de cada página,
referencias entre reglas). 301 reglas de core (con el rules appendix), Space
Marines y Orkos con destacamentos, mejoras, estratagemas y 258 datasheets.
Índice en `data/wahapedia/index/`.

## 2 — ¿Dónde vive el texto de las reglas?

```
pregunta antes de continuar, entonces, cuando le haces una consulta al modelo, el texto que
requiere para contestar ya esta en el repo, o lo que esta en el repo es un indice que le
permite consultar a wahapedia?
```

**Qué se hizo:** solo la explicación: el texto queda en disco local (no en el
repo) y el modelo no consulta Wahapedia en cada pregunta.

## 3 — Reemplazar el RAG por el agente

```
no, así esta bien, así debe ser, sin texto de reglas en el repo, ya es retirar el rag del
pdf y reemplazarlo
```

**Qué se hizo:** agente con herramientas (`get_rules`, `get_codex_index`,
`search_rules`) sobre el endpoint de Azure, con el índice de core en las
instrucciones y seguimiento de conversación con `previous_response_id`. Se
retiraron la ingesta del PDF, BM25 y `pypdf`. Selector de ejército en la
interfaz.

## 4 — Autenticación y base de datos

```
ahora, quiero agregar 2 cosas: autenticación de usuario, nos sugirieron en clase auth0, si
es posible usar ese, con ese, mientras sea free, y crear una database simple, para guardar
perfil de usuario e interacciones, de perfil de usuario pues todo lo relevante para que
auth0 funcione, y en interacciones, me interesa guardar los prompt que haga, las respuestas
no importa, input y output tokens y la metadata del modelo usado, por supuesto con llaves
que relacionen lo relevante, respecto a información de usuario, la intención es que permita
luego integrar con google adsense para usar publicidad para que un posible servicio web
amortigue sus propios gastos
```

**Qué se hizo:** login con Auth0 vía `st.login` (OIDC). SQLite con `users`,
`conversations`, `interactions` y `model_calls` (una fila por llamada al
modelo) y la vista `interaction_usage`. Campos de consentimiento de anuncios
en el perfil.

## 5 — Configuración de Auth0

```
cree el perfil en auth0, en el secrets.toml, completé client_id, client_secret con lo de la
web, dominio no tengo, y en cookie_secret puse cualquier cosa porque no vi como generarlo en
auth0, asumo que es algo de mi lado
```

**Qué se hizo:** se generó un `cookie_secret` aleatorio, se corrigieron las
comillas faltantes del archivo y se indicó dónde está el dominio en Auth0.

```
listo, ya esta el dominio, ya esta callback url y logout url
```

**Qué se hizo:** verificación del dominio y arranque local de la app para
probar el login.

## 6 — Textos de la interfaz

```
listo, parece que auth0 funciona, inicié sesión con google, hay 2 temas de texto a
corregir, al inicio, donde dice "Ingresá para consultar las reglas" realmente da la
impresión que va a entrar a leer las reglas, y realmente no es así, las reglas solo se usan
como referencia, yo pondría más bien una frase que describa la usabilidad esperada, como
"resuelve tus dudas o arbitra tus dudas" o algo así, una frase un poco mejor, tampoco me
gusta este texto: "Fuente: Wahapedia (core rules y codex de Orks, Space Marines). El agente
consulta el índice de reglas y lee solo las que necesita. Generación con Azure AI Foundry."
este quitalo, de este: "Warhammer 40.000 · 11ª edición · reglas de Wahapedia" quita reglas
de wahapedia
```

**Qué se hizo:** "Resolvé tus dudas de reglas y arbitrá las discusiones de la
mesa" en la pantalla de ingreso; se quitaron los otros dos textos.

## 7 — Panel de admin

```
perfecto, hablando de ese interaction_usage, quiero un panel de admin, que sea independiente
del uso normal de la app, allí quiero ver lo que se esta guardando, prompts, la info de
usuario disponible, etc, además un mini dashboard que muestre consumo promedio por usuario y
una proyección del costo a fin de mes según ese consumo, que las credenciales para iniciar
sean 4dmin y pa$$temporal, guardalas en el .env en local
```

**Qué se hizo:** `admin.py`, app aparte con base en solo lectura: KPIs del mes,
costo acumulado con proyección, costo por usuario y tablas de interacciones,
usuarios y llamadas al modelo. Contraseña guardada como hash PBKDF2.

## 8 — Docker y despliegue

```
perfecto, ahora, hay que dockerizar, todo debe quedar funcionando tal cual esta, donde sea
que se despliegue la imagen debo poder entrar con las contraseñas de admin, (seguramente
sería lo mejor re definirlas la primera vez que se ejecute la imagen) y debe quedar de una
forma que sea factible desplegarla en algún servicio que me permita exponer la webapp con
su dominio propio, (realmente se poco de esto, así que importa mucho que sea barato y fácil)
```

**Qué se hizo:** `Dockerfile` con las dos apps detrás de Caddy en un solo
puerto (`/` y `/admin`), disco persistente en `/data`, secretos por variables
de entorno, credenciales de admin temporales con cambio obligatorio en el
primer ingreso y bloqueo ante intentos fallidos. Configuración para Fly.io
(`fly.toml`) y guía `DEPLOY.md`.

## 9 — Ajustes mientras se configuraba Fly

```
cambio menor de texto mientras hago lo de fly, quita:
 "Daniel Peñaranda" de la barra de la izq, como puedo quitar el boton de deploy de la derecha?
```

**Qué se hizo:** se quitó el nombre de la barra lateral y se ocultó el botón
"Deploy" con `toolbarMode = "minimal"`.

```
reiniciala
```

**Qué se hizo:** reinicio de la app y del panel locales.

```
cree la cuenta en Fly, me pidió tarjeta (esperable) luego me hizo un cobro bajo
(autorechazado a menos que yo diga lo contrario) esto es normal? donde estaba haciendo el
pago dice que no me cobran si no por consumo y aún no se consume nada
```

**Qué se hizo:** solo la explicación (retención de verificación de la tarjeta).

## 10 — Despliegue en Fly.io

```
listo, ya cree la cuenta, instala fly para hacer el auth y continuar
```

**Decisión:** nombre de la app `rules-companion`; los secretos los carga el
asistente desde los archivos locales.

**Qué se hizo:** instalación de `flyctl`, creación de la app, del disco y de
los secretos, y deploy en https://rules-companion.fly.dev.

```
listo, puedo hacer preguntas y veo lo que esta dentro de admin
```

**Qué se hizo:** verificación de que las credenciales propias del admin
quedaron guardadas en el disco del servidor.

## 11 — Pantalla de login de Auth0 e ícono

```
[captura de la pantalla de login de Auth0 vista en un celular]
listo, un amigo ensayó y se puede conectar, hay un problema de UI/UX principalmente, el
login se ve así, claramente no da confianza hacer login ahí, entonces creo que hay que
cambiar el texto del login para que no diga ese dev y me imagino que crear un icono
```

**Qué se hizo:** logo servido desde la app (`/app/static/`) para cargarlo en
Auth0, e indicaciones para el nombre del tenant, el branding y las claves
propias de Google.

```
tengo un icono un poco más bonito en @TPF/static/rules_companion_icon.png pero no esta como
png real, tiene un fondo oscuro que debería ser transparente, puedes ajustarlo y usarlo?
```

**Qué se hizo:** recorte del ícono con fondo transparente y versiones de 512,
150 y 32 px, usadas en la app, el panel y Auth0.

## 12 — Listas de ejército de New Recruit

```
en pruebas de usabilidad me dan una idea, poder cargarle tu lista de ejercito, hagamos eso,
pero que cada usuario solo pueda cargar 1 sola lista, que sea compatible solo con el
formato .rosz (al menos inicialmente) de newrecruit
```

**Decisión:** el usuario deja listas de muestra en `samples/`; una lista nueva
reemplaza a la anterior, con confirmación.

```
listo, ya estan los samples
```

**Qué se hizo:** `armylist.py` (lectura segura del `.rosz`, facción,
destacamentos, unidades, warlord y mejoras, vínculo con cada datasheet), tabla
`army_lists` (una por usuario), sección "Tu lista" en la app, uso en
aclaración y arbitraje, pestaña "Listas" en el panel.

```
listo, actualizadas las listas con mejoras, todo lo demás esta bien para el mvp
```

**Qué se hizo:** verificación de la detección de mejoras con las muestras
nuevas.

## 13 — Apagar la máquina de Fly

```
pregunta, si apago la vm en Fly, que se pierde? o la puedo apagar si quiera? no lo he visto,
porque aún no necesito hacer el demo en clase, pero tampco quiero que se pierdan las
interacciones guardadas hasta ahora
```

**Qué se hizo:** solo la explicación (los datos viven en el disco persistente).

## 14 — Exploración: grafo de reglas

```
no, lo último que quiero explorar, pero más en el contexto de pasos futuros, es expresar las
relaciones de las reglas como un grafo, porque ahora lo que hace el agente es ver que le
preguntan, que reglas son útiles, llama esas reglas, las lee, luego ve si necesita
referenciar más reglas y repetir, con un grafo pre computado de relaciones entre reglas se
podria hacer todo con un solo llamado, entonces, quiero ver ese grafo, de reglas y nombres,
con colores para la sección de la regla, puede ser en un html, esto es externo a todo lo
demas y solo exploratorio, no debe considerarse en la construcción de la imagen para Fly ni
nada de uso
```

**Qué se hizo:** `exploracion/grafo_reglas.py` genera un HTML interactivo con
las 940 reglas y 3.460 referencias, coloreadas por sección, con el paquete de
contexto de cada regla a 1 o 2 saltos y su tamaño en tokens. Fuera de la
imagen de Fly.

## 15 — Ajustes finales

```
de la barra lateral, el boton salir aparece de primero, ponlo abajo de limpiar conversación
```

**Qué se hizo:** "Salir" pasó al final de la barra lateral.

```
bueno, ahora necesito un archivo .md en la raíz de TPF que muestre todos mis prompt para
crear esta app, y necesito mover la carpeta de TPF a source_material/peñaranda-iisaia, que
no se rompa nada al moverla
```

**Qué se hizo:** este archivo, y el traslado de la carpeta a
`source_material/peñaranda-iisaia/TPF`.
