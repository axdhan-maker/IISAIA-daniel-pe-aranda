"""Rules Companion 40k - agente de reglas sobre Wahapedia (11a edicion)."""

import time
from pathlib import Path

import streamlit as st

import armylist
import auth
import ui
import userdb
from agent.engine import ToolUse, Turn, arbitrate, army, clarify
from agent.llm import LLMError
from wahapedia import store

LOGO = Path(__file__).resolve().parent / "static" / "logo.png"

st.set_page_config(page_title="Rules Companion 40k", page_icon=str(LOGO))

MODOS = {
    "Aclaración": ":material/help: Aclaración",
    "Arbitraje": ":material/gavel: Arbitraje",
}
EJEMPLOS = {
    "¿Cómo hago para hacer una carga?": "¿Cómo hago para hacer una carga?",
    "¿Qué pasa si fallo un test de battle-shock?": (
        "¿Qué pasa si fallo un test de battle-shock?"
    ),
    "¿Puedo disparar estando trabado en combate?": (
        "¿Puedo disparar estando trabado en combate (engaged)?"
    ),
}
CAPAS = {"core": "Core", "codex": "Codex", "mission": "Misión"}
TIPOS = {
    "core_rule": "regla",
    "army_rule": "regla de ejército",
    "datasheet": "datasheet",
    "detachment_rule": "regla de destacamento",
    "stratagem": "estratagema",
    "enhancement": "mejora",
    "mission_rule": "regla de misión",
}


@st.cache_data(show_spinner=False)
def codices() -> dict[str, str]:
    return {c["id"]: c["name"] for c in store.list_codices()}


@st.cache_data(show_spinner=False)
def destacamentos(codex_id: str) -> dict[str, str]:
    return {d["id"]: d["name"] for d in store.list_detachments(codex_id) or []}


def elegir_ejercito(key: str, etiqueta: str) -> tuple[str | None, str | None]:
    """Codex y destacamento (opcionales). El destacamento depende del codex,
    por eso estos selectores no pueden ir dentro de un st.form."""
    codex = st.selectbox(
        etiqueta,
        list(codices()),
        format_func=codices().get,
        index=None,
        placeholder="Sin especificar",
        key=f"{key}_codex",
    )
    detachment = None
    if codex:
        detachment = st.selectbox(
            "Destacamento",
            list(destacamentos(codex)),
            format_func=destacamentos(codex).get,
            index=None,
            placeholder="Sin especificar",
            key=f"{key}_det_{codex}",
        )
    return codex, detachment


def mi_lista() -> armylist.ArmyList | None:
    """La lista guardada del usuario, si tiene una."""
    data = userdb.get_army_list(user_id)
    if data is None:
        return None
    data.pop("filename", None)
    data.pop("uploaded_at", None)
    return armylist.ArmyList.from_dict(data)


def mostrar_lista(lista: armylist.ArmyList, unidades: bool = True) -> None:
    limite = f"/{lista.points_limit}" if lista.points_limit else ""
    faccion = lista.faction + (f" · {lista.subfaction}" if lista.subfaction else "")
    st.markdown(f"**{lista.name}**")
    st.caption(f"{faccion} · {lista.points}{limite} pts")
    if lista.detachments:
        st.caption("Destacamentos: " + ", ".join(d["name"] for d in lista.detachments))
    if unidades:
        for unit in lista.units:
            marcas = (" · warlord" if unit.warlord else "") + (
                f" · {', '.join(unit.enhancements)}" if unit.enhancements else ""
            )
            st.markdown(f"- {unit.name} ({unit.models}) · {unit.points} pts{marcas}")


@st.dialog("Tu lista de ejército")
def cargar_lista(actual: armylist.ArmyList | None) -> None:
    """Carga (o reemplaza) la lista: se interpreta y se muestra antes de guardar."""
    st.caption(
        "Exportá tu lista desde New Recruit como **.rosz** (11ª edición). "
        "Cada usuario puede tener una sola lista."
    )
    if actual is not None:
        st.warning(f"Ya tenés cargada «{actual.name}». La que subas ahora la reemplaza.")
    archivo = st.file_uploader("Lista (.rosz)", type=["rosz"])
    if archivo is None:
        return
    data = archivo.getvalue()
    try:
        lista = armylist.parse(data)
    except armylist.ListError as error:
        st.error(str(error))
        return
    with st.container(border=True):
        mostrar_lista(lista)
    if lista.codex_id is None:
        st.warning(
            f"Todavía no hay reglas cargadas de {lista.faction}: el agente va a "
            "poder usar la lista, pero solo con las reglas core."
        )
    sin_datasheet = [u.name for u in lista.units if not u.datasheet_href]
    if lista.codex_id and sin_datasheet:
        st.caption("Sin datasheet en el reglamento cargado: " + ", ".join(sin_datasheet))
    accion = "Reemplazar lista" if actual is not None else "Guardar lista"
    if st.button(accion, icon=":material/save:", type="primary", width="stretch"):
        userdb.save_army_list(user_id, archivo.name, data, lista.to_dict())
        st.rerun()


def panel_lista(lista: armylist.ArmyList | None) -> None:
    """Seccion "Tu lista" de la barra lateral."""
    st.subheader("Tu lista")
    if lista is None:
        st.caption("Cargá tu lista de New Recruit para que las respuestas usen tus unidades.")
        if st.button("Cargar lista (.rosz)", icon=":material/upload_file:", width="stretch"):
            cargar_lista(None)
        return
    mostrar_lista(lista, unidades=False)
    with st.expander("Unidades", icon=":material/groups:"):
        mostrar_lista(lista)
    reemplazar, borrar = st.columns(2)
    with reemplazar:
        if st.button("Reemplazar", icon=":material/upload_file:", width="stretch"):
            cargar_lista(lista)
    with borrar:
        with st.popover("Borrar", icon=":material/delete:", width="stretch"):
            st.caption(f"¿Borrar «{lista.name}»?")
            if st.button("Sí, borrar", type="primary", width="stretch"):
                userdb.delete_army_list(user_id)
                st.rerun()


def ejercito_de_lista(lista: armylist.ArmyList) -> dict:
    """Lo que se registra en la base cuando la consulta usa la lista."""
    return {
        "list": lista.name,
        "codex": lista.codex_id,
        "detachments": [d["id"] or d["name"] for d in lista.detachments],
    }


def fuente(rule: dict) -> dict:
    """Lo que se guarda de cada regla consultada para mostrarla como fuente."""
    keys = ("name", "number", "layer", "kind", "section", "source_url", "text", "figures")
    return {k: rule.get(k) for k in keys}


def mostrar_fuentes(fuentes: list[dict]) -> None:
    """Las reglas que leyó el agente, con enlace a Wahapedia y sus diagramas."""
    if not fuentes:
        st.warning("El agente no consultó ninguna regla para esta respuesta.")
        return
    for rule in fuentes:
        nombre = f"{rule['number']} {rule['name']}" if rule.get("number") else rule["name"]
        ruta = " › ".join(rule["section"][:-1])
        tipo = TIPOS.get(rule["kind"], rule["kind"])
        st.markdown(
            f"**[{nombre}]({rule['source_url']})** · {CAPAS[rule['layer']]} · {tipo}"
        )
        if ruta:
            st.caption(ruta)
        with st.expander("Texto de la regla", icon=":material/menu_book:"):
            st.markdown(rule["text"])
            for figura in rule.get("figures") or []:
                st.image(figura["image_url"], caption=figura.get("caption"))


def mostrar_pasos(pasos: list[dict]) -> None:
    for paso in pasos:
        with st.status(paso["title"], type="step", state="complete"):
            st.caption(paso["detail"] or "—")


def responder(turn: Turn) -> dict:
    """Corre el agente mostrando cada consulta a medida que ocurre y transmite
    la respuesta. Devuelve el mensaje para el historial."""
    pasos: list[dict] = []
    inicio = time.monotonic()
    proceso = st.status(":shimmer[Consultando las reglas]", type="compact")

    def texto():
        for event in turn.events():
            if isinstance(event, ToolUse):
                paso = {"title": event.title, "detail": event.detail}
                pasos.append(paso)
                with proceso:
                    mostrar_pasos([paso])
            else:
                yield event

    answer = st.write_stream(texto())
    segundos = time.monotonic() - inicio
    fuentes = [fuente(r) for r in turn.consulted]
    proceso.update(
        label=f"Consultó {len(fuentes)} reglas en {segundos:.0f} s", state="complete"
    )
    with st.expander(f"Fuentes ({len(fuentes)})", icon=":material/menu_book:"):
        mostrar_fuentes(fuentes)
    return {"role": "assistant", "content": answer, "pasos": pasos, "fuentes": fuentes}


def consultar(turn: Turn, *, conversation_id: str, prompt: str, army: dict | None) -> dict | None:
    """Corre la consulta y la registra en la base, haya salido bien o no:
    el prompt, las llamadas al modelo con sus tokens y la latencia."""
    inicio = time.monotonic()
    error = None
    message = None
    try:
        message = responder(turn)
    except LLMError as exc:
        error = str(exc)
        st.error(f"No se pudo consultar el modelo: {error}")
    finally:
        userdb.log_interaction(
            user_id=user_id,
            conversation_id=conversation_id,
            prompt=prompt,
            army=army,
            calls=turn.calls,
            latency_ms=round((time.monotonic() - inicio) * 1000),
            rules_consulted=len(turn.consulted),
            error=error,
        )
    return message


def ejercito(codex: str | None, detachment: str | None) -> dict | None:
    return {"codex": codex, "detachment": detachment} if codex else None


@st.cache_resource(show_spinner=False)
def preparar_base() -> None:
    userdb.init()


def mostrar_respuesta_guardada(message: dict) -> None:
    with st.status(
        f"Consultó {len(message['fuentes'])} reglas", type="compact", state="complete"
    ):
        mostrar_pasos(message["pasos"])
    st.markdown(message["content"])
    with st.expander(f"Fuentes ({len(message['fuentes'])})", icon=":material/menu_book:"):
        mostrar_fuentes(message["fuentes"])


ui.apply_style()

titulo, referencia = st.columns([3, 2], vertical_alignment="bottom")
with titulo:
    st.title("Rules Companion 40k")
with referencia:
    st.caption("Warhammer 40.000 · 11ª edición")
st.divider()

preparar_base()
user_id = auth.require_login()

if not store.CORE_PATH.exists():
    st.error(
        "Todavía no se descargaron las reglas. Corré una vez "
        "`python -m wahapedia sync` desde la carpeta del proyecto."
    )
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.last_response_id = None
    st.session_state.conversation_id = None  # se crea con la primera pregunta

with st.sidebar:
    st.subheader("Configuración")
    modo = st.segmented_control(
        "Modo",
        options=list(MODOS),
        format_func=lambda m: MODOS[m],
        default="Aclaración",
    )
    st.divider()
    lista = mi_lista()
    panel_lista(lista)
    if modo == "Aclaración":
        usar_lista = lista is not None and st.toggle("Usar mi lista en las consultas", value=True)
        if usar_lista:
            ejercito_texto, ejercito_log = armylist.describe(lista), ejercito_de_lista(lista)
        else:
            mi_codex, mi_destacamento = elegir_ejercito("yo", "Tu ejército")
            ejercito_texto, ejercito_log = army(mi_codex, mi_destacamento), ejercito(mi_codex, mi_destacamento)
    st.divider()
    if st.button("Limpiar conversación", icon=":material/delete:", width="stretch"):
        st.session_state.messages = []
        st.session_state.last_response_id = None
        st.session_state.conversation_id = None
        st.rerun()
    auth.sidebar_account()

# --------------------------------------------------------------------------- #
# Modo aclaracion: chat sobre una regla, con seguimiento
# --------------------------------------------------------------------------- #
if modo == "Aclaración":
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                mostrar_respuesta_guardada(message)
            else:
                st.markdown(message["content"])

    prompt = None
    if not st.session_state.messages:
        elegido = st.pills(
            "Ejemplos", list(EJEMPLOS), label_visibility="collapsed"
        )
        if elegido:
            prompt = EJEMPLOS[elegido]

    prompt = st.chat_input("¿Qué regla querés que te aclare?", submit_mode="disable") or prompt

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        if st.session_state.conversation_id is None:
            st.session_state.conversation_id = userdb.start_conversation(user_id, "question")

        with st.chat_message("assistant"):
            # la pregunta encadena con la respuesta anterior: los
            # seguimientos ("¿y si falla?") tienen el contexto
            turn = clarify(
                prompt,
                previous_response_id=st.session_state.last_response_id,
                army_text=ejercito_texto,
            )
            message = consultar(
                turn,
                conversation_id=st.session_state.conversation_id,
                prompt=prompt,
                army=ejercito_log,
            )
            if message is not None:
                st.session_state.messages.append(message)
                st.session_state.last_response_id = turn.response_id

# --------------------------------------------------------------------------- #
# Modo arbitraje: dos posturas enfrentadas
# --------------------------------------------------------------------------- #
else:
    with st.container(border=True):
        st.caption(
            "Describí la situación y lo que sostiene cada jugador. "
            "El árbitro resuelve solo con lo que dicen las reglas."
        )

    ejercito_uno, ejercito_dos = st.columns(2)
    with ejercito_uno:
        if lista is not None and st.toggle("Jugador 1: usar mi lista", value=True):
            texto_uno, log_uno = armylist.describe(lista), ejercito_de_lista(lista)
            st.caption(f"{lista.name} · {lista.faction}")
        else:
            armies_one = elegir_ejercito("j1", "Ejército del jugador 1")
            texto_uno, log_uno = army(*armies_one), ejercito(*armies_one)
    with ejercito_dos:
        armies_two = elegir_ejercito("j2", "Ejército del jugador 2")
        texto_dos, log_dos = army(*armies_two), ejercito(*armies_two)

    with st.form("arbitraje"):
        situacion = st.text_area(
            "Situación en la mesa",
            placeholder=(
                "Mi unidad declaró una carga contra los Boyz y sacó 4 en la "
                "tirada, quedando corta."
            ),
            height=80,
        )
        columna_uno, columna_dos = st.columns(2)
        with columna_uno:
            jugador_uno = st.text_area(
                "Postura del jugador 1",
                placeholder="Puedo disparar igual porque la carga falló.",
                height=120,
            )
        with columna_dos:
            jugador_dos = st.text_area(
                "Postura del jugador 2",
                placeholder="No se puede disparar después de una carga fallida.",
                height=120,
            )
        enviado = st.form_submit_button(
            "Pedir arbitraje", icon=":material/gavel:", type="primary"
        )

    if enviado:
        if not jugador_uno.strip() or not jugador_dos.strip():
            st.warning("Cargá la postura de los dos jugadores.")
        else:
            consultar(
                arbitrate(situacion, jugador_uno, jugador_dos, armies=(texto_uno, texto_dos)),
                conversation_id=userdb.start_conversation(user_id, "dispute"),
                prompt=(
                    f"Situación: {situacion.strip()}\n\n"
                    f"Jugador 1: {jugador_uno.strip()}\n\n"
                    f"Jugador 2: {jugador_dos.strip()}"
                ),
                army={"player_one": log_uno, "player_two": log_dos},
            )
