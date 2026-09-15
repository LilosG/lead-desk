def test_outreach_candidates(client):
    response = client.get('/api/outreach/candidates', params={'limit': 100})
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == len(body['items'])
    assert all(item['established'] is True for item in body['items'])
