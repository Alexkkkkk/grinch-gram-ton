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


def test_internal_health_probe_is_not_blocked_by_scanner_detection(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "test-panel-password")
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.get(
        "/api/health",
        environ_base={"REMOTE_ADDR": "172.17.0.1"},
        headers={"User-Agent": "python-requests/2.25.1"},
    )

    assert response.status_code == 200
