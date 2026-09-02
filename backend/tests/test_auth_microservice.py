from app.auth.main import app, health


def test_auth_microservice_health() -> None:
    assert health() == {"status": "ok", "service": "authentication"}
    paths = set(app.openapi()["paths"])
    assert {"/health", "/api/auth/login", "/api/auth/register", "/api/auth/refresh", "/api/auth/logout"} <= paths
