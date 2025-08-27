# storage.py
import os, mysql.connector
from urllib.parse import urlparse

def _truthy(v: str | None) -> bool:
    return str(v or "").lower() in ("1", "true", "yes", "on")

def db_connect():
    # Prefer a single URL if present (e.g., MYSQL_URL, JAWSDB_URL, CLEARDB_DATABASE_URL)
    url = os.getenv("MYSQL_URL") or os.getenv("JAWSDB_URL") or os.getenv("CLEARDB_DATABASE_URL")
    cfg = {}
    if url:
        p = urlparse(url)
        cfg = dict(
            host=p.hostname,
            port=p.port or 3306,
            user=p.username,
            password=p.password,
            database=(p.path or "/").lstrip("/"),
        )
    else:
        # Fall back to individual env vars; also read Railway-style names
        cfg = dict(
            host=os.getenv("MYSQL_HOST") or os.getenv("MYSQLHOST") or "127.0.0.1",
            port=int(os.getenv("MYSQL_PORT") or os.getenv("MYSQLPORT") or "3306"),
            user=os.getenv("MYSQL_USER") or os.getenv("MYSQLUSER") or "root",
            password=os.getenv("MYSQL_PASSWORD") or os.getenv("MYSQLPASSWORD") or "",
            database=os.getenv("MYSQL_DB") or os.getenv("MYSQLDATABASE") or "finlit",
        )

    # Enable TLS if required by provider (PlanetScale, some managed MySQL)
    if _truthy(os.getenv("MYSQL_SSL")):
        cfg["ssl_disabled"] = False  # mysql-connector enables TLS with this flag

    return mysql.connector.connect(**cfg)
