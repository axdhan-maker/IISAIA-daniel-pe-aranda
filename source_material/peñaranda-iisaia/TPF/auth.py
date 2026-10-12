"""Autenticacion con Auth0 via `st.login` (OpenID Connect).

Streamlit maneja el flujo OIDC completo: redirige a Auth0, valida el ID token
y guarda la identidad en una cookie firmada. Este modulo solo agrega la
pantalla de ingreso y sincroniza el perfil con la base (userdb).

Configuracion en .streamlit/secrets.toml (no se commitea; ver
.streamlit/secrets.toml.example).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

import userdb

LOGO = Path(__file__).resolve().parent / "static" / "logo.png"


def configured() -> bool:
    """True si hay una seccion [auth] en secrets.toml."""
    try:
        return "auth" in st.secrets
    except FileNotFoundError:
        return False


def claims() -> dict:
    """Claims del ID token del usuario logueado (sub, email, name, ...)."""
    return {k: v for k, v in st.user.to_dict().items() if k != "is_logged_in"}


def require_login() -> int:
    """Corta la ejecucion hasta que el usuario ingrese. Devuelve su id en la
    base; el perfil se sincroniza una vez por sesion."""
    if not configured():
        st.error(
            "Falta configurar Auth0: copiá `.streamlit/secrets.toml.example` a "
            "`.streamlit/secrets.toml` y completá los datos de tu aplicación."
        )
        st.stop()

    if not st.user.get("is_logged_in", False):
        with st.container(border=True):
            st.image(str(LOGO), width=72)
            st.subheader("Resolvé tus dudas de reglas y arbitrá las discusiones de la mesa")
            st.caption(
                "Usamos Auth0 para identificarte. Guardamos tu perfil básico y "
                "las preguntas que hacés, no las respuestas."
            )
            st.button(
                "Ingresar", icon=":material/login:", type="primary", on_click=st.login
            )
        st.stop()

    if "user_id" not in st.session_state:
        st.session_state.user_id = userdb.upsert_user(claims())
    return st.session_state.user_id


def sidebar_account() -> None:
    """Boton para salir."""
    if st.button("Salir", icon=":material/logout:", width="stretch"):
        st.logout()
