from app.repositories.outreach import OutreachRepository


class _Cursor:
    def __init__(self):
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return []


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


class _Pool:
    def __init__(self, cursor):
        self._cursor = cursor

    def connection(self):
        return _Connection(self._cursor)


def test_recent_generated_drafts_types_nullable_uuid_parameter():
    cursor = _Cursor()
    repo = OutreachRepository(_Pool(cursor))

    rows = repo.recent_generated_drafts(exclude_id=None)

    assert rows == []
    assert "%s::uuid is null" in cursor.query
    assert "q.id <> %s::uuid" in cursor.query
    assert cursor.params == (None, None, 25)
