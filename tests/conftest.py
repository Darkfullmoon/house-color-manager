import io
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from models import db  # noqa: E402


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "TESTING": True,
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "CSRF_ENABLED": False,
        "SECRET_KEY": "test",
        "ADMIN_PASSWORD": "Test*123",
        "DEFAULT_PASSWORD": "Test*123",
    })
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def login(client, username, password, **kw):
    return client.post("/login", data={"username": username, "password": password}, **kw)


@pytest.fixture
def anon_client(app):
    """A browser that has not logged in."""
    return app.test_client()


@pytest.fixture
def client(app):
    """Logged in as the administrator (ADM), so the pre-login tests keep working."""
    c = app.test_client()
    assert login(c, "ADM", "Test*123").status_code == 302
    return c


@pytest.fixture
def make_user(app):
    """Create an active user who has already set their own password."""

    def _make(username="USR", password="User#1234", must_change=False):
        from werkzeug.security import generate_password_hash
        from models import User
        with app.app_context():
            u = User(username=username, full_name=f"User {username}", role="user",
                     password_hash=generate_password_hash(password),
                     must_change_password=must_change)
            db.session.add(u)
            db.session.commit()
            return u.to_dict()

    return _make


@pytest.fixture
def user_client(app, make_user):
    make_user("USR", "User#1234")
    c = app.test_client()
    assert login(c, "USR", "User#1234").status_code == 302
    return c


def png_bytes(color=(30, 90, 160), size=(4, 4)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def make_house(client):
    """Create a house (optionally with one image and colors) through the API."""

    def _make(name, colors=(), image=False):
        if image:
            resp = client.post("/api/houses", data={
                "house_name": name,
                "images": (io.BytesIO(png_bytes()), "house.png"),
            }, content_type="multipart/form-data")
        else:
            resp = client.post("/api/houses", json={"house_name": name})
        assert resp.status_code == 201, resp.get_json()
        house = resp.get_json()
        for c in colors:
            payload = {"r": 200, "g": 180, "b": 150, "manufacturing": "TOA", "model": "M1",
                       "house_id": house["id"], **c}
            r = client.post("/api/colors", json=payload)
            assert r.status_code == 201, r.get_json()
        return client.get(f"/api/houses/{house['id']}").get_json()

    return _make
