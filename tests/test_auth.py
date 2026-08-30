"""Authentication boundary tests."""

from web.app import create_app


def test_dashboard_requires_auth_and_login_creates_session(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-panel-password")
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD_HASH_B64", raising=False)

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert (
        client.post(
            "/login",
            json={"username": "admin", "password": "wrong-password"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/login",
            json={"username": "admin", "password": "test-panel-password"},
        ).status_code
        == 200
    )
    assert client.get("/api/status").status_code == 200
