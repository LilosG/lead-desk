from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import get_settings


settings = get_settings()

pool = ConnectionPool(
    conninfo=settings.database_url,
    min_size=1,
    max_size=10,
    timeout=10,
    open=False,
    kwargs={
        "row_factory": dict_row,
        "autocommit": True,
    },
)


def open_pool() -> None:
    pool.open(wait=True)


def close_pool() -> None:
    pool.close()
