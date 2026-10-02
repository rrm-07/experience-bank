"""Storage layer. Postgres in production (Supabase), SQLite locally for tests."""
import os
from sqlalchemy import create_engine, text


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///experience_bank.db"
    # Supabase/Heroku-style URLs start with postgres:// ; SQLAlchemy needs a driver name.
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


engine = create_engine(_url(), pool_pre_ping=True, pool_size=3, max_overflow=2) \
    if not _url().startswith("sqlite") else create_engine(_url())

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS experiences (
        id INTEGER PRIMARY KEY {auto},
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        what_i_did TEXT NOT NULL,
        skills TEXT NOT NULL,
        outcome TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY {auto},
        user_id TEXT NOT NULL,
        company TEXT NOT NULL,
        role TEXT NOT NULL,
        deadline TEXT,
        stage TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_exp_user ON experiences(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_app_user ON applications(user_id)",
]


def init() -> None:
    auto = "GENERATED ALWAYS AS IDENTITY" if engine.dialect.name == "postgresql" else "AUTOINCREMENT"
    with engine.begin() as conn:
        for stmt in _SCHEMA:
            conn.execute(text(stmt.format(auto=auto)))
