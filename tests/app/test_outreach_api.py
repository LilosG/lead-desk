def test_outreach_candidates(client):
    response = client.get('/api/outreach/candidates', params={'limit': 100})
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == len(body['items'])
    # Volume first: candidates are not limited to established leads, but
    # within the same contact channel, established leads sort ahead.
    emailable = [item for item in body['items'] if item['email']]
    flags = [bool(item['established']) for item in emailable]
    assert flags == sorted(flags, reverse=True)
