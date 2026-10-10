"""Database connection and migration helpers."""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "supabase" / "migrations"


def connect(url: str) -> psycopg.Connection:
    # TCP keepalives keep the idle connection alive (and detect a dead one) while collectors run.
    return psycopg.connect(
        url,
        autocommit=True,
        row_factory=dict_row,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )
