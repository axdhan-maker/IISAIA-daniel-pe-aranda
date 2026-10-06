# TP 2 — API de reglas y memoria para un Rules Companion de Warhammer 40k

Un `openapi.yaml` que describe el servicio que va a usar el agente del proyecto final: un asistente que responde preguntas de reglas de Warhammer 40k y resuelve disputas entre jugadores citando las reglas. No hay nada implementado: el entregable es el contrato.

## Cómo se lee

Pegar el contenido de [openapi.yaml](openapi.yaml) en [editor.swagger.io](https://editor.swagger.io).

## Qué me propuse construir

Ya tengo un prototipo que responde con un RAG básico: el PDF gratuito de reglas cortado en chunks y un match por frecuencia de palabras. Funciona mal y sólo mejora si trae muchos chunks. Este contrato es el pivote: en vez de buscar texto parecido, un agente navega las reglas siguiendo el índice de Wahapedia, que además se actualiza cuando cambian las reglas.

El servicio tiene dos responsabilidades:

- **Reglas:** scrapear Wahapedia y guardar las reglas en una estructura `codex → regla`, donde cada regla conoce las reglas que referencia. El agente tiene el índice en su contexto y pide el texto completo sólo de las reglas que necesita.
- **Memoria por usuario:** guardar un resumen de la conversación antes de que expire la caché del proveedor del modelo, y recuperarlo en una pregunta nueva sólo si es relevante.

## Decisiones que tomé yo
Usar web scrapping en lugar de pdf
Usar indice y retrieval agentico en lugar de chunks y distancias
Core rules siempre se buscan
Agregar las reglas de codex y misiones
Distintas layers de reglas, generales a especificas
References con href en cada regla para que el agente siga la cadena de reglas
Imagenes solo en core rules, referenciadas, sin descargar y hostear
El servicio ordena los contextos por relevancia, pero decide el agente si usarlos.


## Qué salió mal y cómo lo corregí

Inicialmente core rules y codex estaban al mismo nivel, no jerarquico como debe ser. Corregido en el prompt 2.

## Prompts

El registro completo está en [prompts.md](prompts.md).
