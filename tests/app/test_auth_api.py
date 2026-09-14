from tests.app.conftest import TEST_PASSWORD, TEST_USERNAME


def test_protected_api_rejects_unauthenticated(public_client):
    response = public_client.get("/api/overview")
    assert response.status_code == 401
    assert response.json()["detail"] == "authentication required"


def test_login_session_and_logout(public_client):
    bad = public_client.post(
        "/api/auth/login",
        json={"username": TEST_USERNAME, "password": "wrong-password"},
    )
    assert bad.status_code == 401

    login = public_client.post(
        "/api/auth/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True

    cookie = login.headers.get("set-cookie", "")
    assert "lead_desk_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie

    session = public_client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json()["username"] == TEST_USERNAME

    protected = public_client.get("/api/overview")
    assert protected.status_code == 200

    logout = public_client.post("/api/auth/logout")
    assert logout.status_code == 200

    after = public_client.get("/api/overview")
    assert after.status_code == 401
