"""Base de datos de la app: perfiles de usuario e interacciones con el agente.

SQLite en un archivo (data/app.db), sin servidor. Cuatro tablas:

    users           perfil de Auth0 (una fila por `sub`)
    conversations   una por chat de aclaracion o por arbitraje
    interactions    cada pregunta del usuario (el prompt, no la respuesta)
    model_calls     cada llamada al modelo dentro de una interaccion: el
                    agente hace varias (una por vuelta de herramientas), cada
                    una con sus tokens y la metadata del modelo
    army_lists      la lista de ejercito del usuario (.rosz de New Recruit):
                    una por usuario, la clave es user_id

La vista `interaction_usage` suma los tokens por interaccion.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent
# APP_DB_PATH permite ubicar la base en otro lado (en Docker: el volumen /data)
DB_PATH = Path(os.getenv("APP_DB_PATH") or ROOT / "data" / "app.db")
PROVIDER = "azure-ai-foundry"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                INTEGER PRIMARY KEY,
    auth0_sub         TEXT NOT NULL UNIQUE,  -- id estable de Auth0: "google-oauth2|1234"
    identity_provider TEXT,                  -- prefijo del sub: google-oauth2, auth0, github...
    email             TEXT,
    email_verified    INTEGER,
    name              TEXT,
    nickname          TEXT,
    given_name        TEXT,
    family_name       TEXT,
    picture           TEXT,
    locale            TEXT,
    -- consentimiento para anuncios personalizados (AdSense). NULL = no se pregunto
    ads_consent       TEXT CHECK (ads_consent IN ('granted', 'denied')),
    ads_consent_at    TEXT,
    created_at        TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,
    session_count     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,  -- uuid
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode       TEXT NOT NULL CHECK (mode IN ('question', 'dispute')),
    started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interactions (
    id              INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    prompt          TEXT NOT NULL,   -- lo que escribio el usuario
    army            TEXT,            -- JSON: codex y destacamento elegidos
    status          TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    error           TEXT,
    latency_ms      INTEGER,
    rules_consulted INTEGER
);

CREATE TABLE IF NOT EXISTS model_calls (
    id                   INTEGER PRIMARY KEY,
    interaction_id       INTEGER NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
    step                 INTEGER NOT NULL,  -- vuelta del agente, desde 0
    provider             TEXT NOT NULL,
    model                TEXT,              -- el que reporta la respuesta
    reasoning_effort     TEXT,
    tool_choice          TEXT,
    tool_calls           INTEGER NOT NULL,  -- herramientas pedidas en esta vuelta
    response_id          TEXT,
    previous_response_id TEXT,
    input_tokens         INTEGER,
    cached_tokens        INTEGER,
    output_tokens        INTEGER,
    reasoning_tokens     INTEGER,
    latency_ms           INTEGER
);

CREATE TABLE IF NOT EXISTS army_lists (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,  -- una por usuario
    name        TEXT NOT NULL,
    filename    TEXT NOT NULL,
    codex_id    TEXT,           -- NULL si la faccion no tiene reglas cargadas
    faction     TEXT NOT NULL,
    detachments TEXT NOT NULL,  -- JSON: [{"name", "id"}]
    points      INTEGER NOT NULL,
    summary     TEXT NOT NULL,  -- JSON: la lista ya interpretada (armylist.ArmyList)
    file        BLOB NOT NULL,  -- el .rosz original, para re-interpretarlo si cambia el parser
    uploaded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_conversations_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS ix_interactions_user ON interactions(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_interactions_conversation ON interactions(conversation_id);
CREATE INDEX IF NOT EXISTS ix_model_calls_interaction ON model_calls(interaction_id);

CREATE VIEW IF NOT EXISTS interaction_usage AS
SELECT i.id AS interaction_id,
       i.user_id,
       i.conversation_id,
       i.created_at,
       COUNT(c.id)                        AS model_calls,
       GROUP_CONCAT(DISTINCT c.model)     AS models,
       COALESCE(SUM(c.input_tokens), 0)     AS input_tokens,
       COALESCE(SUM(c.cached_tokens), 0)    AS cached_tokens,
       COALESCE(SUM(c.output_tokens), 0)    AS output_tokens,
       COALESCE(SUM(c.reasoning_tokens), 0) AS reasoning_tokens
FROM interactions i
LEFT JOIN model_calls c ON c.interaction_id = i.id
GROUP BY i.id;
"""

PROFILE_CLAIMS = (
    "email", "name", "nickname", "given_name", "family_name", "picture", "locale",
)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Conexion con claves foraneas activas; commit al salir sin error."""
    path = path or DB_PATH  # se resuelve al llamar: las pruebas lo apuntan a otra base
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------- #
# usuarios
# --------------------------------------------------------------------------- #

def upsert_user(claims: dict, path: Path | None = None) -> int:
    """Crea o actualiza el perfil a partir de los claims del ID token de Auth0.

    Se llama una vez por sesion de la app: actualiza los datos del perfil
    (pueden cambiar en el proveedor), `last_seen_at` y `session_count`.
    Devuelve el id interno del usuario.
    """
    sub = claims["sub"]
    profile = {k: claims.get(k) for k in PROFILE_CLAIMS}
    verified = claims.get("email_verified")
    stamp = now()
    with connect(path) as conn:
        conn.execute(
            f"""
            INSERT INTO users (auth0_sub, identity_provider, email_verified,
                               {", ".join(PROFILE_CLAIMS)}, created_at, last_seen_at)
            VALUES (:sub, :provider, :verified,
                    {", ".join(":" + k for k in PROFILE_CLAIMS)}, :stamp, :stamp)
            ON CONFLICT (auth0_sub) DO UPDATE SET
                email_verified = excluded.email_verified,
                {", ".join(f"{k} = excluded.{k}" for k in PROFILE_CLAIMS)},
                last_seen_at = excluded.last_seen_at,
                session_count = users.session_count + 1
            """,
            profile | {
                "sub": sub,
                "provider": sub.split("|", 1)[0] if "|" in sub else None,
                "verified": None if verified is None else int(bool(verified)),
                "stamp": stamp,
            },
        )
        return conn.execute("SELECT id FROM users WHERE auth0_sub = ?", (sub,)).fetchone()["id"]


def set_ads_consent(user_id: int, granted: bool, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute(
            "UPDATE users SET ads_consent = ?, ads_consent_at = ? WHERE id = ?",
            ("granted" if granted else "denied", now(), user_id),
        )


# --------------------------------------------------------------------------- #
# lista de ejercito
# --------------------------------------------------------------------------- #

def save_army_list(user_id: int, filename: str, data: bytes, army: dict,
                   path: Path | None = None) -> None:
    """Guarda la lista del usuario; si ya tenia una, la reemplaza."""
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO army_lists (user_id, name, filename, codex_id, faction, detachments,
                                    points, summary, file, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                name = excluded.name, filename = excluded.filename,
                codex_id = excluded.codex_id, faction = excluded.faction,
                detachments = excluded.detachments, points = excluded.points,
                summary = excluded.summary, file = excluded.file,
                uploaded_at = excluded.uploaded_at
            """,
            (
                user_id, army["name"], filename, army["codex_id"], army["faction"],
                json.dumps(army["detachments"], ensure_ascii=False), army["points"],
                json.dumps(army, ensure_ascii=False), data, now(),
            ),
        )


def get_army_list(user_id: int, path: Path | None = None) -> dict | None:
    """La lista interpretada del usuario (con `filename` y `uploaded_at`), o None."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT summary, filename, uploaded_at FROM army_lists WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["summary"]) | {"filename": row["filename"], "uploaded_at": row["uploaded_at"]}


def delete_army_list(user_id: int, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute("DELETE FROM army_lists WHERE user_id = ?", (user_id,))


# --------------------------------------------------------------------------- #
# interacciones
# --------------------------------------------------------------------------- #

def start_conversation(user_id: int, mode: str, path: Path | None = None) -> str:
    conversation_id = str(uuid.uuid4())
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, mode, started_at) VALUES (?, ?, ?, ?)",
            (conversation_id, user_id, mode, now()),
        )
    return conversation_id


def log_interaction(
    *,
    user_id: int,
    conversation_id: str,
    prompt: str,
    army: dict | None,
    calls: list[dict],
    latency_ms: int,
    rules_consulted: int,
    error: str | None = None,
    path: Path | None = None,
) -> int:
    """Guarda una pregunta y las llamadas al modelo que hizo el agente para
    responderla. Si fallo a mitad de camino, quedan las llamadas que llego a
    hacer y el error."""
    with connect(path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO interactions (conversation_id, user_id, created_at, prompt, army,
                                      status, error, latency_ms, rules_consulted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id, user_id, now(), prompt,
                json.dumps(army, ensure_ascii=False) if army else None,
                "error" if error else "ok", error, latency_ms, rules_consulted,
            ),
        )
        interaction_id = cursor.lastrowid
        conn.executemany(
            """
            INSERT INTO model_calls (interaction_id, step, provider, model, reasoning_effort,
                                     tool_choice, tool_calls, response_id, previous_response_id,
                                     input_tokens, cached_tokens, output_tokens,
                                     reasoning_tokens, latency_ms)
            VALUES (:interaction_id, :step, :provider, :model, :reasoning_effort,
                    :tool_choice, :tool_calls, :response_id, :previous_response_id,
                    :input_tokens, :cached_tokens, :output_tokens,
                    :reasoning_tokens, :latency_ms)
            """,
            [{"interaction_id": interaction_id, "provider": PROVIDER} | call for call in calls],
        )
    return interaction_id


if __name__ == "__main__":
    init()
    print(f"base lista -> {DB_PATH}")
