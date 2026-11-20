from werkzeug.security import generate_password_hash

from app import create_app
from conftest import login
from models import User, db


def html(resp):
    return resp.get_data(as_text=True)


def create_default_user(app, username):
    """A freshly created account: default password, must set a new one."""
    with app.app_context():
        db.session.add(User(username=username, full_name="New User", role="user",
                            password_hash=generate_password_hash(app.config["DEFAULT_PASSWORD"]),
                            must_change_password=True))
        db.session.commit()


def set_active(app, username, active):
    with app.app_context():
        User.query.filter_by(username=username).one().active = active
        db.session.commit()


def admin_id(app):
    with app.app_context():
        return User.query.filter_by(username="ADM").one().id


# ---- Protection ---------------------------------------------------------------- #
def test_anonymous_is_redirected_or_401(anon_client):
    for path in ("/", "/colors", "/houses/new", "/manufacturers", "/export.xlsx"):
        r = anon_client.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"], path
    for path in ("/api/houses", "/api/colors", "/api/manufacturers", "/api/stats", "/uploads/x.png"):
        assert anon_client.get(path).status_code == 401, path
    assert anon_client.get("/api/health").status_code == 200
    assert anon_client.get("/login").status_code == 200


def test_admin_login_and_logout(anon_client):
    r = login(anon_client, "ADM", "nope")
    assert r.status_code == 200 and "Incorrect username or password." in html(r)
    r = login(anon_client, " adm ", "Test*123")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert anon_client.get("/").status_code == 200
    anon_client.post("/logout")
    assert anon_client.get("/").status_code == 302


def test_next_never_leaves_site(anon_client):
    for bad in ("https://evil.example", "//evil.example"):
        r = anon_client.post(f"/login?next={bad}", data={"username": "ADM", "password": "Test*123"})
        assert r.status_code == 302 and r.headers["Location"] == "/"
        anon_client.post("/logout")
    r = anon_client.post("/login?next=/colors", data={"username": "ADM", "password": "Test*123"})
    assert r.headers["Location"] == "/colors"


def test_first_login_forces_password_change(app, anon_client):
    create_default_user(app, "NEW")
    assert login(anon_client, "new", "Test*123").headers["Location"].endswith("/change-password")
    assert anon_client.get("/").headers["Location"].endswith("/change-password")
    assert anon_client.get("/api/houses").status_code == 403

    r = anon_client.post("/change-password", data={"current": "Test*123", "new": "abcdefgh", "confirm": "abcdefgh"})
    body = html(r)
    assert "uppercase" in body and "digit" in body and "special" in body
    r = anon_client.post("/change-password", data={"current": "Test*123", "new": "Test*123", "confirm": "Test*123"})
    assert "default password" in html(r)
    r = anon_client.post("/change-password", data={"current": "wrong", "new": "Paint#2026", "confirm": "Paint#2026"})
    assert "Current password is incorrect." in html(r)
    r = anon_client.post("/change-password", data={"current": "Test*123", "new": "Paint#2026", "confirm": "Paint#2027"})
    assert "do not match" in html(r)

    r = anon_client.post("/change-password", data={"current": "Test*123", "new": "Paint#2026", "confirm": "Paint#2026"})
    assert r.status_code == 302
    assert anon_client.get("/").status_code == 200
    anon_client.post("/logout")
    assert login(anon_client, "NEW", "Test*123").status_code == 200       # default password no longer works
    assert login(anon_client, "NEW", "Paint#2026").status_code == 302


def test_password_rules():
    from auth import password_problems
    assert password_problems("Paint#2026", "Test*123") == []
    assert len(password_problems("short1A", "Test*123")) == 2            # too short, no special character
    assert password_problems("Test*123", "Test*123") == ["must be different from the default password"]
    assert len(password_problems("", "Test*123")) == 4


# ---- Roles --------------------------------------------------------------------- #
def test_user_cannot_reach_admin_areas(user_client):
    assert user_client.get("/manufacturers").status_code == 403
    assert user_client.post("/api/manufacturers", json={"name": "Jotun"}).status_code == 403
    assert user_client.delete("/api/manufacturers/1").status_code == 403
    assert user_client.get("/api/manufacturers").status_code == 200
    body = html(user_client.get("/"))
    assert "/manufacturers" not in body and 'href="/users"' not in body


def test_admin_sees_admin_menus(client):
    body = html(client.get("/"))
    assert 'href="/manufacturers"' in body
    assert client.get("/manufacturers").status_code == 200


def test_user_can_save_color_with_new_manufacturer(user_client):
    h = user_client.post("/api/houses", json={"house_name": "Villa U"}).get_json()
    r = user_client.post("/api/colors", json={"color_name": "Sand", "r": 1, "g": 2, "b": 3,
                                              "manufacturing": "Jotun", "model": "X", "house_id": h["id"]})
    assert r.status_code == 201
    assert "Jotun" in [m["name"] for m in user_client.get("/api/manufacturers").get_json()]


def test_disabled_user_is_logged_out(app, user_client):
    set_active(app, "USR", False)
    assert user_client.get("/api/houses").status_code == 401
    assert user_client.get("/").status_code == 302


def test_csrf_required_when_enabled(tmp_path):
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite://", "TESTING": True,
                      "UPLOAD_FOLDER": str(tmp_path / "up"), "SECRET_KEY": "test",
                      "ADMIN_PASSWORD": "Test*123", "DEFAULT_PASSWORD": "Test*123"})
    c = app.test_client()
    page = html(c.get("/login"))
    assert 'name="csrf_token"' in page
    assert login(c, "ADM", "Test*123").status_code == 400                 # no token
    with c.session_transaction() as s:
        token = s["_csrf"]
    r = c.post("/login", data={"username": "ADM", "password": "Test*123", "csrf_token": token})
    assert r.status_code == 302
    with c.session_transaction() as s:
        token = s["_csrf"]
    assert c.post("/api/houses", json={"house_name": "No token"}).status_code == 400
    r = c.post("/api/houses", json={"house_name": "With token"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 201
    assert f'content="{token}"' in html(c.get("/"))
    with app.app_context():
        db.session.remove()
        db.drop_all()


# ---- User management (admin) --------------------------------------------------- #
def test_admin_creates_user_who_must_change_password(client, anon_client):
    r = client.post("/api/users", json={"username": "ab1", "full_name": "X"})
    assert r.status_code == 422 and "3 uppercase English letters" in r.get_json()["fields"]["username"]
    r = client.post("/api/users", json={"username": "ADM", "full_name": "X"})
    assert r.status_code == 422 and "reserved" in r.get_json()["fields"]["username"]
    r = client.post("/api/users", json={"username": "ABC", "full_name": " "})
    assert r.status_code == 422 and "full_name" in r.get_json()["fields"]

    r = client.post("/api/users", json={"username": "abc", "full_name": "Somchai"})
    assert r.status_code == 201
    assert r.get_json()["username"] == "ABC" and r.get_json()["must_change_password"] is True
    r = client.post("/api/users", json={"username": "ABC", "full_name": "Dup"})
    assert r.status_code == 422 and "already exists" in r.get_json()["fields"]["username"]

    assert login(anon_client, "ABC", "Test*123").headers["Location"].endswith("/change-password")


def test_reset_and_disable(client, make_user, anon_client):
    u = make_user("USR", "User#1234")
    assert client.post(f"/api/users/{u['id']}/reset-password").get_json()["must_change_password"] is True
    assert login(anon_client, "USR", "User#1234").status_code == 200          # old password no longer works
    assert login(anon_client, "USR", "Test*123").status_code == 302
    anon_client.post("/logout")

    r = client.put(f"/api/users/{u['id']}", json={"active": False, "full_name": "Renamed"})
    assert r.get_json()["active"] is False and r.get_json()["full_name"] == "Renamed"
    assert login(anon_client, "USR", "Test*123").status_code == 200           # disabled
    assert client.put(f"/api/users/{u['id']}", json={"active": True}).get_json()["active"] is True
    assert login(anon_client, "USR", "Test*123").status_code == 302


def test_admin_row_is_not_manageable(client, app):
    adm = admin_id(app)
    assert client.put(f"/api/users/{adm}", json={"active": False}).status_code == 404
    assert client.post(f"/api/users/{adm}/reset-password").status_code == 404
    assert client.put("/api/users/9999", json={"active": False}).status_code == 404
    assert "ADM" not in [u["username"] for u in client.get("/api/users").get_json()]


def test_users_area_is_admin_only(user_client):
    assert user_client.get("/users").status_code == 403
    assert user_client.get("/api/users").status_code == 403
    assert user_client.post("/api/users", json={"username": "XYZ", "full_name": "x"}).status_code == 403


def test_users_page_lists_accounts(client, make_user):
    make_user("USR", "User#1234")
    body = html(client.get("/users"))
    assert "USR" in body and "Reset password" in body and 'href="/users"' in body


def test_expired_session_asks_for_login_not_a_csrf_error(tmp_path):
    """A page left open past the session lifetime: saving must lead to the login page."""
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite://", "TESTING": True,
                      "UPLOAD_FOLDER": str(tmp_path / "up"), "SECRET_KEY": "test",
                      "ADMIN_PASSWORD": "Test*123", "DEFAULT_PASSWORD": "Test*123"})
    c = app.test_client()                                   # no session at all, CSRF enabled
    r = c.post("/api/houses", json={"house_name": "X"}, headers={"X-CSRF-Token": "stale"})
    assert r.status_code == 401 and r.get_json()["error"] == "Please log in."
    r = c.post("/logout", data={"csrf_token": "stale"})
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    with app.app_context():
        db.session.remove()
        db.drop_all()
