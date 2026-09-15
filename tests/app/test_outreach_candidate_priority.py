from app.repositories.outreach import OutreachRepository


class FakeCursor:
    def __init__(self):
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


class FakePool:
    def __init__(self):
        self.cursor_instance = FakeCursor()

    def connection(self):
        return FakeConnection(self.cursor_instance)


def test_outreach_candidates_enforce_viability_and_priority_contract():
    pool = FakePool()
    repo = OutreachRepository(pool)

    assert repo.list_candidates(limit=37) == []

    query = " ".join(pool.cursor_instance.query.split())

    assert "coalesce(w.review_count, 0) >= 10" in query
    assert "coalesce(f.needs_manual_check, false) = false" in query
    assert "not exists ( select 1 from outreach_queue q where q.place_id = w.place_id )" in query
    assert "not exists ( select 1 from suppression s where lower(s.email) = lower(coalesce(w.emails_found[1], '')) )" in query

    email_first = query.index(
        "case when cardinality(coalesce(w.emails_found, '{}'::text[])) > 0 then 0 else 1 end"
    )
    established_volume = query.index(
        "case when coalesce(w.review_count, 0) >= 15 then 0 else 1 end"
    )
    trading = query.index("case when seg.confirmed_trading then 0 else 1 end")
    gap_score = query.index("w.total_score desc")

    assert email_first < established_volume < trading < gap_score
    assert pool.cursor_instance.params == (37,)
