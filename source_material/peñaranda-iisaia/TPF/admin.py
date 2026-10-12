"""Panel de admin: lo que guarda la base y cuanto cuesta el modelo.

Es una app aparte de la de los jugadores, con credenciales propias (.env) y
acceso de solo lectura a la base. Se corre solo en la maquina local:

    python -m streamlit run admin.py --server.port 8502 --server.address 127.0.0.1
"""

from __future__ import annotations

import calendar
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import admin_auth
import armylist
import env
import ui
import userdb

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

MAX_ATTEMPTS = 5
WINDOW_DAYS = 7  # ventana para estimar el ritmo de consumo
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
ACCENT = "#ffc000"
MUTED = "#9a9a9a"

st.set_page_config(page_title="Admin · Rules Companion 40k", page_icon=str(ROOT / "static" / "logo.png"), layout="wide")
ui.apply_style()


# --------------------------------------------------------------------------- #
# acceso
# --------------------------------------------------------------------------- #

def login() -> None:
    """Formulario de ingreso; corta la ejecucion hasta que las credenciales
    coincidan. Si son las temporales, exige definir unas propias antes de
    seguir. Hay dos frenos a la fuerza bruta: MAX_ATTEMPTS por sesion y el
    bloqueo global de admin_auth."""
    if st.session_state.get("admin"):
        return
    st.title("Panel de admin")

    if st.session_state.get("must_change"):
        change_credentials()
        st.stop()

    attempts = st.session_state.setdefault("attempts", 0)
    locked = admin_auth.locked_for()
    if attempts >= MAX_ATTEMPTS or locked:
        wait = f" Probá de nuevo en {locked / 60:.0f} min." if locked else ""
        st.error(f"Demasiados intentos fallidos.{wait}")
        st.stop()
    with st.form("login"):
        user = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        entered = st.form_submit_button("Entrar", icon=":material/login:", type="primary")
    if entered:
        creds = admin_auth.verify(user, password)
        if creds is not None:
            st.session_state.must_change = creds.temporary
            st.session_state.admin = not creds.temporary
            st.rerun()
        st.session_state.attempts = attempts + 1
        st.error("Usuario o contraseña incorrectos.")
    st.stop()


def change_credentials() -> None:
    """Primer ingreso con credenciales temporales: hay que definir otras."""
    st.warning(
        "Entraste con credenciales temporales. Definí un usuario y una "
        "contraseña propios para continuar; las temporales dejan de valer."
    )
    with st.form("credenciales"):
        user = st.text_input("Usuario nuevo", value=admin_auth.current().user)
        password = st.text_input(
            "Contraseña nueva", type="password",
            help=f"Al menos {admin_auth.MIN_LENGTH} caracteres.",
        )
        repeated = st.text_input("Repetí la contraseña", type="password")
        saved = st.form_submit_button("Guardar", icon=":material/key:", type="primary")
    if saved:
        found = admin_auth.problems(user, password, repeated)
        if found:
            for problem in found:
                st.error(problem)
            return
        admin_auth.save(user, password)
        st.session_state.must_change = False
        st.session_state.admin = True
        st.rerun()


# --------------------------------------------------------------------------- #
# datos
# --------------------------------------------------------------------------- #

def read(query: str) -> pd.DataFrame:
    """Consulta en modo solo lectura: el panel no puede modificar la base."""
    if not userdb.DB_PATH.exists():
        return pd.DataFrame()
    uri = f"file:{userdb.DB_PATH.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        return pd.read_sql_query(query, conn)


def load() -> dict[str, pd.DataFrame]:
    users = read("SELECT * FROM users ORDER BY last_seen_at DESC")
    interactions = read("""
        SELECT i.id, i.created_at, i.user_id, u.email, u.name, c.mode, i.conversation_id,
               i.prompt, i.army, i.status, i.error, i.latency_ms, i.rules_consulted,
               x.model_calls, x.models, x.input_tokens, x.cached_tokens,
               x.output_tokens, x.reasoning_tokens
        FROM interactions i
        JOIN users u ON u.id = i.user_id
        JOIN conversations c ON c.id = i.conversation_id
        JOIN interaction_usage x ON x.interaction_id = i.id
        ORDER BY i.created_at DESC
    """)
    calls = read("SELECT * FROM model_calls ORDER BY interaction_id DESC, step")
    lists = read("""
        SELECT l.uploaded_at, u.email, l.name, l.faction, l.codex_id, l.detachments,
               l.points, l.filename, l.summary
        FROM army_lists l JOIN users u ON u.id = l.user_id
        ORDER BY l.uploaded_at DESC
    """)
    for frame, column in ((users, "created_at"), (users, "last_seen_at"),
                          (interactions, "created_at"), (lists, "uploaded_at")):
        if not frame.empty:
            frame[column] = pd.to_datetime(frame[column], utc=True)
    return {"users": users, "interactions": interactions, "calls": calls, "lists": lists}


def cost(frame: pd.DataFrame, prices: dict[str, float]) -> pd.Series:
    """Costo en USD. Los tokens cacheados son parte de los de entrada y se
    cobran aparte; los de razonamiento ya estan dentro de los de salida."""
    uncached = frame["input_tokens"] - frame["cached_tokens"].fillna(0)
    return (
        uncached * prices["input"]
        + frame["cached_tokens"].fillna(0) * prices["cached"]
        + frame["output_tokens"] * prices["output"]
    ) / 1_000_000


def projection(month: pd.DataFrame, now: datetime) -> dict:
    """Costo a fin de mes segun el consumo promedio por usuario.

    Ritmo = costo por usuario activo y por dia en los ultimos WINDOW_DAYS (o
    desde la primera pregunta del mes, si es mas reciente). Proyeccion = lo
    gastado + ritmo x usuarios activos del mes x dias que faltan.
    """
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    month_end = now.replace(day=days_in_month, hour=23, minute=59, second=59)
    remaining_days = (month_end - now).total_seconds() / 86400
    spent = month["cost"].sum()
    if month.empty:
        return {"spent": 0.0, "projected": 0.0, "per_user_day": 0.0, "users": 0,
                "remaining_days": remaining_days, "window_days": 0.0}

    start = max(now - timedelta(days=WINDOW_DAYS), month["created_at"].min())
    window = month[month["created_at"] >= start]
    window_days = max((now - start).total_seconds() / 86400, 1.0)
    window_users = max(window["user_id"].nunique(), 1)
    per_user_day = window["cost"].sum() / window_users / window_days
    users = month["user_id"].nunique()
    return {
        "spent": spent,
        "projected": spent + per_user_day * users * remaining_days,
        "per_user_day": per_user_day,
        "users": users,
        "remaining_days": remaining_days,
        "window_days": window_days,
    }


# --------------------------------------------------------------------------- #
# graficos
# --------------------------------------------------------------------------- #

def cumulative_chart(month: pd.DataFrame, now: datetime, forecast: dict) -> alt.Chart:
    """Costo acumulado real (linea solida) y proyectado (punteada) del mes."""
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    daily = (
        month.assign(day=month["created_at"].dt.day)
        .groupby("day")["cost"].sum()
        .reindex(range(1, now.day + 1), fill_value=0.0)
        .cumsum()
    )
    actual = pd.DataFrame({"dia": daily.index, "costo": daily.values, "serie": "Real"})
    future = pd.DataFrame({
        "dia": [now.day, days_in_month],
        "costo": [forecast["spent"], forecast["projected"]],
        "serie": "Proyección",
    })
    data = pd.concat([actual, future])
    tooltip = [
        alt.Tooltip("serie:N", title=""),
        alt.Tooltip("dia:Q", title="Día"),
        alt.Tooltip("costo:Q", title="USD acumulado", format="$.4f"),
    ]
    color = alt.Color(
        "serie:N",
        scale=alt.Scale(domain=["Real", "Proyección"], range=[ACCENT, MUTED]),
        legend=alt.Legend(title=None, orient="top"),
    )
    dash = alt.StrokeDash(
        "serie:N",
        scale=alt.Scale(domain=["Real", "Proyección"], range=[[1, 0], [6, 4]]),
        legend=None,
    )
    x = alt.X("dia:Q", title="Día del mes", scale=alt.Scale(domain=[1, days_in_month]),
              axis=alt.Axis(tickMinStep=1, grid=False))
    y = alt.Y("costo:Q", title="USD acumulado", axis=alt.Axis(format="$.2f", gridOpacity=0.15))
    lines = alt.Chart(data).mark_line(strokeWidth=2).encode(x=x, y=y, color=color, strokeDash=dash)
    points = alt.Chart(data).mark_point(size=80, filled=True, opacity=0).encode(
        x=x, y=y, tooltip=tooltip
    )  # objetivo de hover mas grande que la linea
    return (lines + points).properties(height=280)


def per_user_chart(per_user: pd.DataFrame) -> alt.Chart:
    return alt.Chart(per_user).mark_bar(color=ACCENT, cornerRadiusEnd=4, height=14).encode(
        x=alt.X("costo:Q", title="USD en el mes", axis=alt.Axis(format="$.4f", gridOpacity=0.15)),
        y=alt.Y("usuario:N", sort="-x", title=None),
        tooltip=[
            alt.Tooltip("usuario:N", title="Usuario"),
            alt.Tooltip("preguntas:Q", title="Preguntas"),
            alt.Tooltip("costo:Q", title="USD", format="$.4f"),
            alt.Tooltip("costo_por_pregunta:Q", title="USD por pregunta", format="$.4f"),
        ],
    ).properties(height=max(120, 36 * len(per_user)))


# --------------------------------------------------------------------------- #
# pagina
# --------------------------------------------------------------------------- #

login()

with st.sidebar:
    st.subheader("Precios (USD / 1M tokens)")
    st.caption("Por defecto, los del .env. Verificalos contra la factura de Azure.")
    prices = {
        "input": st.number_input("Entrada", value=float(env.get("price_input_per_1m", "0.20")), min_value=0.0, step=0.01, format="%.3f"),
        "cached": st.number_input("Entrada cacheada", value=float(env.get("price_cached_input_per_1m", "0.02")), min_value=0.0, step=0.001, format="%.3f"),
        "output": st.number_input("Salida", value=float(env.get("price_output_per_1m", "1.20")), min_value=0.0, step=0.01, format="%.3f"),
    }
    st.divider()
    if st.button("Actualizar datos", icon=":material/refresh:", width="stretch"):
        st.rerun()
    if st.button("Salir", icon=":material/logout:", width="stretch"):
        st.session_state.admin = False
        st.rerun()

st.title("Panel de admin")
data = load()
users, interactions, calls, lists = data["users"], data["interactions"], data["calls"], data["lists"]
if interactions.empty:
    st.info("Todavía no hay interacciones registradas.")
    st.stop()

interactions["cost"] = cost(interactions, prices)
calls["cost"] = cost(calls, prices)

now = datetime.now(timezone.utc)
month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
month = interactions[interactions["created_at"] >= month_start]
forecast = projection(month, now)

tab_dash, tab_inter, tab_users, tab_lists, tab_calls = st.tabs(
    ["Dashboard", "Interacciones", "Usuarios", "Listas", "Llamadas al modelo"]
)

with tab_dash:
    st.caption(f"Mes en curso: {MESES[now.month - 1]} {now.year} (UTC)")
    active = forecast["users"]
    questions = len(month)
    with st.container(horizontal=True):
        st.metric("Usuarios activos en el mes", active, f"{len(users)} registrados", delta_color="off", border=True)
        st.metric("Preguntas en el mes", questions, border=True)
        st.metric("Costo del mes", f"${forecast['spent']:.4f}", border=True)
        st.metric("Proyección a fin de mes", f"${forecast['projected']:.4f}", border=True)
        st.metric(
            "Costo promedio por usuario",
            f"${forecast['spent'] / active:.4f}" if active else "—",
            border=True,
        )
        st.metric(
            "Tokens por pregunta",
            f"{month['input_tokens'].mean():,.0f} / {month['output_tokens'].mean():,.0f}" if questions else "—",
            "entrada / salida",
            delta_color="off",
            border=True,
        )

    left, right = st.columns([3, 2])
    with left, st.container(border=True):
        st.markdown("**Costo acumulado y proyección**")
        st.altair_chart(cumulative_chart(month, now, forecast), width="stretch")
        st.caption(
            f"Ritmo: ${forecast['per_user_day']:.4f} por usuario activo y por día "
            f"(últimos {forecast['window_days']:.1f} días) × {active} usuarios × "
            f"{forecast['remaining_days']:.1f} días restantes."
        )
    with right, st.container(border=True):
        st.markdown("**Consumo por usuario en el mes**")
        per_user = (
            month.assign(usuario=month["email"].fillna(month["name"]))
            .groupby("usuario")
            .agg(preguntas=("id", "count"), costo=("cost", "sum"),
                 tokens_entrada=("input_tokens", "sum"), tokens_cacheados=("cached_tokens", "sum"),
                 tokens_salida=("output_tokens", "sum"))
            .reset_index()
        )
        per_user["costo_por_pregunta"] = per_user["costo"] / per_user["preguntas"]
        st.altair_chart(per_user_chart(per_user), width="stretch")
        st.dataframe(
            per_user.sort_values("costo", ascending=False),
            hide_index=True,
            column_config={
                "usuario": "Usuario",
                "preguntas": "Preguntas",
                "costo": st.column_config.NumberColumn("USD", format="$%.4f"),
                "costo_por_pregunta": st.column_config.NumberColumn("USD / pregunta", format="$%.4f"),
                "tokens_entrada": st.column_config.NumberColumn("Entrada", format="localized"),
                "tokens_cacheados": st.column_config.NumberColumn("Cacheados", format="localized"),
                "tokens_salida": st.column_config.NumberColumn("Salida", format="localized"),
            },
        )

with tab_inter:
    emails = sorted(interactions["email"].dropna().unique())
    who = st.multiselect("Usuario", emails, placeholder="Todos")
    shown = interactions[interactions["email"].isin(who)] if who else interactions
    st.caption("Elegí una fila para ver las llamadas al modelo de esa pregunta.")
    picked = st.dataframe(
        shown[["created_at", "email", "mode", "prompt", "army", "status", "model_calls",
               "input_tokens", "cached_tokens", "output_tokens", "cost", "latency_ms",
               "rules_consulted", "error"]],
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "created_at": st.column_config.DatetimeColumn("Fecha", format="YYYY-MM-DD HH:mm"),
            "email": "Usuario",
            "mode": "Modo",
            "prompt": st.column_config.TextColumn("Prompt", width="large"),
            "army": "Ejército",
            "status": "Estado",
            "model_calls": "Llamadas",
            "input_tokens": st.column_config.NumberColumn("Entrada", format="localized"),
            "cached_tokens": st.column_config.NumberColumn("Cacheados", format="localized"),
            "output_tokens": st.column_config.NumberColumn("Salida", format="localized"),
            "cost": st.column_config.NumberColumn("USD", format="$%.4f"),
            "latency_ms": st.column_config.NumberColumn("Latencia (ms)", format="localized"),
            "rules_consulted": "Reglas",
            "error": "Error",
        },
    )
    rows = picked.selection.rows
    if rows:
        chosen = shown.iloc[rows[0]]
        with st.container(border=True):
            st.markdown(f"**Pregunta #{chosen['id']}** · {chosen['email']}")
            st.text(chosen["prompt"])
            st.dataframe(
                calls[calls["interaction_id"] == chosen["id"]].drop(columns=["id", "interaction_id"]),
                hide_index=True,
                column_config={"cost": st.column_config.NumberColumn("USD", format="$%.5f")},
            )

with tab_users:
    st.dataframe(
        users,
        hide_index=True,
        column_config={
            "picture": st.column_config.ImageColumn("Foto", width="small"),
            "created_at": st.column_config.DatetimeColumn("Alta", format="YYYY-MM-DD HH:mm"),
            "last_seen_at": st.column_config.DatetimeColumn("Última visita", format="YYYY-MM-DD HH:mm"),
            "email_verified": st.column_config.CheckboxColumn("Email verificado"),
            "ads_consent": "Consentimiento anuncios",
        },
    )

with tab_lists:
    if lists.empty:
        st.info("Ningún usuario cargó una lista todavía.")
    else:
        st.caption(f"{len(lists)} listas (una por usuario). Elegí una para ver sus unidades.")
        picked_list = st.dataframe(
            lists.drop(columns=["summary"]),
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "uploaded_at": st.column_config.DatetimeColumn("Cargada", format="YYYY-MM-DD HH:mm"),
                "email": "Usuario",
                "name": "Lista",
                "faction": "Facción",
                "codex_id": "Codex",
                "detachments": "Destacamentos",
                "points": st.column_config.NumberColumn("Puntos", format="localized"),
                "filename": "Archivo",
            },
        )
        if picked_list.selection.rows:
            row = lists.iloc[picked_list.selection.rows[0]]
            with st.container(border=True):
                st.markdown(f"**{row['name']}** · {row['email']}")
                st.code(armylist.describe(armylist.ArmyList.from_dict(json.loads(row["summary"]))), language=None)

with tab_calls:
    st.dataframe(
        calls,
        hide_index=True,
        column_config={"cost": st.column_config.NumberColumn("USD", format="$%.5f")},
    )
