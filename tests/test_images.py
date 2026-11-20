import io

from conftest import png_bytes

MULTIPART = "multipart/form-data"


def imgs(n):
    return [(io.BytesIO(png_bytes()), f"p{i}.png") for i in range(n)]


def test_a_house_can_hold_any_number_of_images(client):
    r = client.post("/api/houses", data={"house_name": "Big", "images": imgs(7)}, content_type=MULTIPART)
    assert r.status_code == 201 and r.get_json()["image_count"] == 7
    hid = r.get_json()["id"]
    r = client.post(f"/api/houses/{hid}/images", data={"images": imgs(4)}, content_type=MULTIPART)
    assert r.status_code == 201
    assert client.get(f"/api/houses/{hid}").get_json()["image_count"] == 11


def test_house_page_never_locks_uploads(client):
    h = client.post("/api/houses", data={"house_name": "Big", "images": imgs(8)}, content_type=MULTIPART).get_json()
    body = client.get(f"/houses/{h['id']}").get_data(as_text=True)
    assert "8 image(s)" in body and "Images 8/" not in body
    assert 'type="button" disabled' not in body
    assert "max_images" not in body


def test_add_house_page_offers_capture(client):
    body = client.get("/houses/new").get_data(as_text=True)
    assert "js-capture" in body and "Capture screen" in body
    assert "Ctrl+V" in body
    assert "data-max-images" not in body
