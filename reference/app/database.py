"""Small synchronous MySQL helper layer for API handlers."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any, cast

import pymysql
from pymysql.cursors import DictCursor
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from .config import DB_CONFIG

_engine = create_engine(
    URL.create(
        "mysql+pymysql",
        username=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        database=DB_CONFIG["database"],
    ),
    pool_size=8,
    max_overflow=8,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={
        "charset": "utf8mb4",
        "connect_timeout": 5,
        "read_timeout": 20,
        "write_timeout": 20,
    },
)


def get_connection() -> pymysql.connections.Connection:
    return _engine.raw_connection()


@contextmanager
def db_cursor(dict_cursor: bool = True) -> Iterator[tuple[Any, Any]]:
    conn = get_connection()
    cursor = conn.cursor(DictCursor if dict_cursor else None)
    try:
        yield conn, cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
    with db_cursor() as (_, cursor):
        cursor.execute(sql, params)
        return cast(dict[str, Any] | None, cursor.fetchone())


def fetch_all(sql: str, params: Any | None = None) -> list[dict[str, Any]]:
    with db_cursor() as (_, cursor):
        cursor.execute(sql, params)
        return cast(list[dict[str, Any]], list(cursor.fetchall()))


def execute(sql: str, params: Any | None = None) -> int:
    with db_cursor() as (_, cursor):
        affected = cursor.execute(sql, params)
        return 0 if affected is None else int(affected)


def executemany(sql: str, params: Iterable[tuple[Any, ...]]) -> int:
    with db_cursor() as (_, cursor):
        affected = cursor.executemany(sql, params)
        return 0 if affected is None else int(affected)
