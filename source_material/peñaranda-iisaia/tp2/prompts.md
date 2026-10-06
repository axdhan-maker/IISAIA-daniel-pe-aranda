# Prompts — TP 2

El registro del proceso, en orden, dentro de una sola conversación.

---

## 1 — Prompt inicial

```
respecto al tp2: me gustaría que el openapi.yaml me ayudara para el proyecto final del curso,
el proyecto es un rules companion de warhammer 40k, dado que las reglas pueden ser complicadas
para los jugadores nuevos, quiero que un modelo pueda ayudar a responder preguntas y resolver
conflictos entre reglas, tendría 2 modos principales de uso, uno de consulta base, estilo:
¿como hago para disparar después de moverme y que algunos de mis modelos ya no puedan ver a la
unidad rival? y otro modo de resolver conflictos, al estilo: en este escenario, el jugador 1
dice esto, el jugador 2 dice esto, cual es la resolución correcta? citando las reglas, ya tengo
un prototipo que funciona con un rag muy primitivo, lo que hice fue tomar el pdf de reglas
gratis, dividirlo en chunks, usar un algoritmo de match de chunks muy primitivo, que cuenta
frecuencias e importancia de las palabras y trae los chunks según eso, no funciona tan bien,
hay que aumentar mucho el número de chunks para que funcione, entonces quiero pivotar el rag
por un retrieval agentico, que no funcione sobre el pdf si no sobre un scrapping de la web
wahapedia, como esta web se actualiza según se van actualizando las reglas, yo creo que es un
buen uso para construir el documento openapi, la idea es que el documento sea la interfaz que
se encarga del "scrapping" dado que el wahapedia las reglas ya estan organizadas y siguen un
"indice", y ese indice esta referenciado donde se usan las reglas, el objetivo sería hacer
scrapping e ir guardando eso en una estructura lógica para que luego un agente pueda consultar
esta estructura lógica basandose principalmente en el indice de las reglas, en el contexto de
este agente puede vivir el indice, y también como usar los metodos que puede llamar para
consultar las reglas, como el GET/codex/rules/id_rule, que debería retornar la regla especifica
de un codex en particular, un post podría usarse para que el agente decida guardar el contexto
de la conversación despues de un tiempo, antes que pase el tiempo en que la caché esta viva por
lado del servicio del modelo, que haga un resumen de la conversación y la guarde, para ese
usuario, y otro que permita llamar ese contexto cuando el mismo usuario haga otra pregunta,
pero lo llama si la pregunta es relevante, por ahora solo es armar el documento de estas
interacciones
```

**Qué buscaba:**
Quería construir un contrato que sirva para el proyecto final, que no fuese un esfuerzo aislado. Como no manejo completamente los endpoint, describí a mi modo lo que quería, con los elementos de arquitectura que tenia claros, reemplazar el RAG del pdf por un scrapping de una página web, usar la sugerencia en clase de usar un retrieval agentico y expandir a reglas que se referencian entre si, por índice, incluyendo nuevos documentos, e implementar una memoria para el usuario.
El agente retornó un archivo con paths y operaciones para esto, 7 paths y 9 operaciones: codex (GET/POST), índice de reglas, regla completa, sync de scraping (POST asíncrono con 202 + GET de estado) y contextos por usuario (GET con búsqueda por relevancia, POST, DELETE). Basandose en el ejemplo provisto para la actividad.

---

## 2 — Separar core, codex y misión, con precedencia

```
core rules debería llamarse siempre, no debería ser un codex más, si yo pregunto algo como:
los hellblaster pueden disparar incluso si estan en engagement? debería llamar lo relevante de
core rules para disparo y lo relevante del codex para los hellblaster, si además se especifica
el destacamento debe traer las reglas del destacamento. o sea, un prompt del usuario debería
poder generar distintos call, multiples a core, multiples a codex, y si el prompt es tipo
arbitraje, diferentes codex, acabo de recordar, se necesita también un apartado para reglas de
misión, las reglas tienen un nivel que sería: mision > codex > core
```

**Qué buscaba:**
corregir una decisión del modelo equivocada, en la v0.1 el core rules se trataba como un codex más. Pero el core no es una facción, aplica a todas las preguntas y su índice tiene que estar siempre (si es relevante) en el contexto del agente. Además faltaban cosas, las reglas de destacamento (sólo aplican si el ejército juega ese destacamento) y las reglas de misión, que son la capa que precede cualquier decisión cuando hay conflicto (misión > codex > core).

Retornó la v0.2: tres capas con paths propios (/core/rules, /codices/{codexId}/..., /mission-packs/{packId}/rules), destacamentos dependientes de su codex, un campo layer en cada regla para aplicar la precedencia, href en las referencias para que el agente las siga, el scraping movido a un /syncs general que recibe la capa en el body.

---

## 3 — Pregunta: ¿las imágenes van en el contrato?

```
no se si el manejo de imagenes también debe incluirse en este contrato, el core rules tiene
diagramas ilustrativos de algunas reglas, es normal que vayan en este tipo de contratos? o no
es el lugar correcto?
```

**Qué buscaba:**
Estaba explorando ideas, pero antes de pedir un cambio, entender si las imágenes debian ser parte del contrato o no. El modelo explicó que OpenAPI también describe respuestas binarias y propuso separar la descripción del diagrama (en la regla) del archivo (endpoint aparte). Luego me dejó  una decisión si guardar una copia de la imagen o sólo referenciar la URL de Wahapedia. No cambió el yaml. Mi respuesta fue solo referenciar la imagen y cargarla de la web.

---

## 4 — Diagramas: sólo core, sólo URL, el agente lee la descripción

```
ok, primero, solo en el core rules y solo referenciar desde wahapedia, cuando se haga el
scrapping, colocamos una descripción (si no la tienen ya) de los diagramas y el agente solo va
a ver eso, la descripción, el usuario sería el que vea el diagrama como imagen.
```

**Qué buscaba:**
Que el agente efectuara ya la decisión de referenciar las imagenes, pero que solo fueran del core de reglas, hubo 2 opciones de descripción de la imagen, para pasar texto y no la imagen directamente al modelo, se generan una vez al scrapear, las guardamos y usamos esa, en caso que el scrap ya tenga descripción guarda las dos, el agente lee la descripción solamente, no procesa la imagen.

Retorno la versión la v0.3: GET /core/rules/{ruleId} devuelve un CoreRule (una Rule más figures). Cada Figure tiene description (lo que lee el agente), description_source (wahapedia o generated, para saber si el texto es original o lo escribió un modelo) e image_url apuntando a la web. No hay endpoint  binario (el que trae imagen).

---

