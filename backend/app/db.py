from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.paths import get_data_dir


def get_database_url() -> str:
    return os.getenv("APP_DATABASE_URL", f"sqlite:///{get_data_dir() / 'tasks.sqlite3'}")


@lru_cache(maxsize=1)
def get_engine():
    database_url = get_database_url()
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, connect_args={"check_same_thread": False})


def reset_db_runtime() -> None:
    get_engine.cache_clear()


def init_db() -> None:
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
