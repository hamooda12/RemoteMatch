import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.middleware.security_headers import (
    SecurityHeadersMiddleware,
)


def build_settings(
    **overrides: object,
) -> Settings:
    values: dict[str, object] = {
        "database_url": ("postgresql+psycopg://user:password@localhost/test"),
        "session_secret": "s" * 40,
        "environment": "development",
        "debug": False,
        "cors_origins": "http://localhost:5173",
        "allowed_hosts": "localhost,testserver",
    }
    values.update(overrides)

    return Settings(**values)


def test_settings_parse_frontend_origins_and_hosts() -> None:
    settings = build_settings(
        cors_origins=("http://localhost:5173/, http://127.0.0.1:5173"),
        allowed_hosts=("localhost, 127.0.0.1, testserver"),
    )

    assert settings.cors_origin_list == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert settings.allowed_host_list == [
        "localhost",
        "127.0.0.1",
        "testserver",
    ]


def test_settings_reject_wildcard_authenticated_cors() -> None:
    with pytest.raises(
        ValidationError,
        match="Wildcard CORS origins",
    ):
        build_settings(
            cors_origins="*",
        )


def test_settings_reject_insecure_same_site_none_cookie() -> None:
    with pytest.raises(
        ValidationError,
        match="SameSite=None",
    ):
        build_settings(
            session_cookie_same_site="none",
        )


@pytest.mark.parametrize(
    (
        "overrides",
        "message",
    ),
    [
        (
            {
                "debug": True,
            },
            "Debug mode",
        ),
        (
            {
                "cors_origins": ("http://frontend.example.com"),
            },
            "must use HTTPS",
        ),
        (
            {
                "session_secret": ("replace_with_a_random_value_of_at_least_32_characters"),
            },
            "must be random",
        ),
    ],
)
def test_settings_reject_insecure_production_configuration(
    overrides: dict[str, object],
    message: str,
) -> None:
    production_values: dict[str, object] = {
        "environment": "production",
        "cors_origins": "https://frontend.example.com",
        "allowed_hosts": "api.example.com",
    }
    production_values.update(overrides)

    with pytest.raises(
        ValidationError,
        match=message,
    ):
        build_settings(**production_values)


def test_valid_production_settings_enable_secure_cookies() -> None:
    settings = build_settings(
        environment="production",
        session_secret="p" * 40,
        session_cookie_same_site="none",
        cors_origins="https://frontend.example.com",
        allowed_hosts="api.example.com",
    )

    assert settings.secure_cookies is True
    assert settings.session_cookie_same_site == "none"


def test_api_responses_include_security_headers(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == ("nosniff")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == ("camera=(), microphone=(), geolocation=()")

    if get_settings().environment != "production":
        assert "strict-transport-security" not in response.headers


def test_production_security_headers_include_hsts() -> None:
    application = FastAPI()
    application.add_middleware(
        SecurityHeadersMiddleware,
        production=True,
    )

    @application.get("/")
    async def test_endpoint() -> dict[str, str]:
        return {
            "status": "ok",
        }

    with TestClient(application) as production_client:
        response = production_client.get("/")

    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == ("max-age=31536000; includeSubDomains")


def test_untrusted_host_is_rejected(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/health",
        headers={
            "Host": "untrusted.example",
        },
    )

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_allowed_frontend_origin_receives_cors_headers(
    client: TestClient,
) -> None:
    origin = get_settings().cors_origin_list[0]

    response = client.get(
        "/api/v1/health",
        headers={
            "Origin": origin,
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (origin)
    assert response.headers["access-control-allow-credentials"] == "true"

    preflight_response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": ("Content-Type, X-CSRF-Token"),
        },
    )

    assert preflight_response.status_code == 200
    assert preflight_response.headers["access-control-allow-origin"] == origin
    assert "POST" in preflight_response.headers["access-control-allow-methods"]


def test_disallowed_frontend_origin_receives_no_cors_access(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/health",
        headers={
            "Origin": "https://untrusted.example",
        },
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
