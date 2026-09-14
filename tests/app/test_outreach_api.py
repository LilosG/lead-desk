from app.core.database import pool


MAUZY_PLACE_ID = "ChIJOUNgSehU2YARadzzd7bpc68"


def cleanup():
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from outreach_queue_events
                where place_id = %s
                """,
                (MAUZY_PLACE_ID,),
            )
            cur.execute(
                "delete from outreach_queue where place_id = %s",
                (MAUZY_PLACE_ID,),
            )
        conn.commit()


def test_outreach_candidates(client):
    response = client.get('/api/outreach/candidates', params={'limit': 100})
    assert response.status_code == 200
    body = response.json()
    assert body['total'] > 0
    assert all(item['established'] is True for item in body['items'])


def test_outreach_verification_gate_and_conflict(client):
    cleanup()
    try:
        queued = client.post(
            f'/api/outreach/{MAUZY_PLACE_ID}',
            json={'channel': 'phone'},
        )
        assert queued.status_code == 201
        item = queued.json()
        assert item['status'] == 'queued'
        assert item['verification_status'] == 'pending'

        blocked = client.patch(
            f"/api/outreach/items/{item['id']}",
            json={
                'expected_version': item['version'],
                'status': 'draft_ready',
            },
        )
        assert blocked.status_code == 422

        ready = client.patch(
            f"/api/outreach/items/{item['id']}",
            json={
                'expected_version': item['version'],
                'verification_status': 'verified',
                'verification_note': 'Manually verified before outreach.',
                'status': 'draft_ready',
            },
        )
        assert ready.status_code == 200
        state = ready.json()
        assert state['status'] == 'draft_ready'
        assert state['verification_status'] == 'verified'
        assert state['version'] == item['version'] + 1

        stale = client.patch(
            f"/api/outreach/items/{item['id']}",
            json={
                'expected_version': item['version'],
                'status': 'contacted',
            },
        )
        assert stale.status_code == 409

        queue = client.get('/api/outreach')
        assert queue.status_code == 200
        assert any(row['id'] == item['id'] for row in queue.json()['items'])
    finally:
        cleanup()
