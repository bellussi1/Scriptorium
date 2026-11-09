"""Upload-time source-language guard for the fixed en -> pt-BR scope."""
from __future__ import annotations

from io import BytesIO

import pytest
from flask import Flask

from src.api.blueprints.security_routes import create_security_blueprint

ENGLISH = (
    b"The old lighthouse keeper climbed the narrow stairs every evening before "
    b"sunset. He carried a small lantern and a notebook in which he wrote down "
    b"the weather and the names of the birds that rested on the rocks. "
) * 10

FRENCH = (
    "Le vieux gardien de phare montait les escaliers étroits chaque soir avant "
    "le coucher du soleil. Il portait une petite lanterne et un carnet dans "
    "lequel il notait le temps et les noms des oiseaux posés sur les rochers. "
).encode("utf-8") * 10

PORTUGUESE = (
    "O velho faroleiro subia as escadas estreitas todas as noites antes do pôr "
    "do sol. Levava uma pequena lanterna e um caderno no qual anotava o tempo "
    "e os nomes das aves que descansavam nas rochas. "
).encode("utf-8") * 10


@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(create_security_blueprint(str(tmp_path)))
    with app.test_client() as test_client:
        yield test_client


def _upload(client, data: bytes, filename: str, operation: str):
    return client.post(
        "/api/upload",
        data={
            "file": (BytesIO(data), filename),
            "operation": operation,
        },
        content_type="multipart/form-data",
    )


def test_english_translate_upload_is_accepted(client):
    response = _upload(client, ENGLISH, "book.txt", "translate")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source_language"] == "en"
    assert payload["language_confidence"] > 0.8


def test_french_translate_upload_is_rejected(client):
    response = _upload(client, FRENCH, "book.txt", "translate")
    assert response.status_code == 400
    payload = response.get_json()
    assert "only translates English" in payload["error"]
    assert payload["source_language"] == "fr"


def test_portuguese_refine_upload_is_accepted(client):
    response = _upload(client, PORTUGUESE, "book.epub.txt", "refine")
    assert response.status_code == 200
    assert response.get_json()["source_language"] == "pt"


def test_english_refine_upload_is_rejected(client):
    response = _upload(client, ENGLISH, "book.txt", "refine")
    assert response.status_code == 400
    assert "Portuguese file" in response.get_json()["error"]
