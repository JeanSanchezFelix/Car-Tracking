"""Shared database settings for the API and ETL."""

from collections.abc import Mapping

from psycopg2 import ProgrammingError
from psycopg2.extensions import make_dsn, parse_dsn


def render_connection_config(env: Mapping[str, str]) -> dict:
    """Resolve one cloud connection; URL credentials always take precedence."""
    url = (env.get("DATABASE_URL") or env.get("RENDER_URL") or "").strip()
    if not url:
        raise RuntimeError("Configure DATABASE_URL or RENDER_URL with the Render PostgreSQL URL.")
    url = url.removeprefix("jdbc:")
    if not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("The Render database URL must use postgresql:// or postgres://.")
    try:
        params = parse_dsn(url)
    except ProgrammingError:
        # Driver parsing errors can contain the original URL, including its password.
        raise RuntimeError("The Render PostgreSQL URL is invalid.") from None
    try:
        port = int(params.get("port", "5432"))
    except ValueError:
        raise RuntimeError("The Render database port must be an integer from 1 to 65535.") from None
    if not 1 <= port <= 65535:
        raise RuntimeError("The Render database port must be an integer from 1 to 65535.")

    # Older DataGrip/JDBC configurations keep credentials separately. Fill missing
    # URL credentials only; never override credentials supplied by the URL.
    for name, variable in (("user", "RENDER_USER"), ("password", "RENDER_PASSWORD")):
        if not params.get(name) and env.get(variable):
            params[name] = env[variable]
    if not all(params.get(name) for name in ("host", "dbname", "user", "password")):
        raise RuntimeError("The Render connection needs a host, database, username, and password.")

    return {
        "dsn": make_dsn(**params),
        "sslmode": "require",
        "options": "-c search_path=public",
        "connect_timeout": 10,
    }


def database_connection_config(env: Mapping[str, str]) -> dict:
    # Render supplies RENDER=true. Never use the development Docker settings there.
    hosted = env.get("RENDER", "").strip().lower() == "true"
    target = "render" if hosted else env.get("DB_TARGET", "local").strip().lower()
    if target == "render":
        return render_connection_config(env)
    if target != "local":
        raise RuntimeError("DB_TARGET must be local or render.")
    return {
        "host": env.get("LOCAL_HOST", "localhost"),
        "port": int(env.get("LOCAL_PORT", "5432")),
        "user": env.get("LOCAL_USER"),
        "password": env.get("LOCAL_PASSWORD"),
        "dbname": env.get("LOCAL_DB"),
        "options": "-c search_path=public",
        "connect_timeout": 10,
    }
