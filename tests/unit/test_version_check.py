"""Update-check tests: disabled by default, fork-only when enabled, no network."""
from __future__ import annotations

from flask import Flask

from src.api.blueprints.version_routes import create_version_blueprint
from src.utils import version_checker


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self) -> dict:
        return self._payload


class _State:
    def get_all_translations(self) -> dict:
        return {}


def _forbid_network(*args, **kwargs):
    raise AssertionError("network call attempted")


def _client():
    app = Flask(__name__)
    app.register_blueprint(create_version_blueprint(_State()))
    return app.test_client()


def test_update_check_disabled_by_default(monkeypatch):
    monkeypatch.setattr(version_checker, "UPDATE_CHECK_ENABLED", False)
    monkeypatch.setattr(version_checker.requests, "get", _forbid_network)
    version_checker.invalidate_cache()

    result = version_checker.check_for_update(force=True)

    assert result["update_available"] is False
    assert result["latest"] is None
    assert result["release_url"] == ""
    assert result["error"] == "update check disabled"


def test_update_check_uses_the_fork_when_enabled(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return _Response(
            200,
            {
                "tag_name": "v9.9.9",
                "name": "v9.9.9",
                "html_url": "https://github.com/bellussi1/TranslateBooksWithLLMs/releases/tag/v9.9.9",
                "body": "notes",
                "published_at": "2026-01-01T00:00:00Z",
            },
        )

    monkeypatch.setattr(version_checker, "UPDATE_CHECK_ENABLED", True)
    monkeypatch.setattr(version_checker.requests, "get", fake_get)
    monkeypatch.setattr(
        version_checker,
        "GITHUB_RELEASES_API",
        "https://api.github.com/repos/bellussi1/TranslateBooksWithLLMs/releases/latest",
    )
    monkeypatch.setattr(
        version_checker,
        "GITHUB_TAGS_API",
        "https://api.github.com/repos/bellussi1/TranslateBooksWithLLMs/tags",
    )
    version_checker.invalidate_cache()

    result = version_checker.check_for_update(force=True)

    assert result["update_available"] is True
    assert result["latest"] == "9.9.9"
    assert calls == [
        "https://api.github.com/repos/bellussi1/TranslateBooksWithLLMs/releases/latest"
    ]
    assert "hydropix" not in calls[0]
    version_checker.invalidate_cache()


def test_version_check_route_is_offline_when_disabled(monkeypatch):
    monkeypatch.setattr(version_checker, "UPDATE_CHECK_ENABLED", False)
    monkeypatch.setattr(version_checker.requests, "get", _forbid_network)

    response = _client().get("/api/version/check")

    assert response.status_code == 200
    data = response.get_json()
    assert data["update_available"] is False
    assert data["error"] == "update check disabled"


def test_update_route_refuses_when_disabled(monkeypatch):
    monkeypatch.setattr(version_checker, "UPDATE_CHECK_ENABLED", False)

    response = _client().post("/api/version/update", json={})

    assert response.status_code == 409
    assert response.get_json()["error"] == "update_disabled"
