from fastapi.testclient import TestClient

from app.main import SAMPLE, app

c = TestClient(app)


def test_head_requests_answer_200():
    # Link checkers and uptime monitors send HEAD; it must not look like a dead link.
    for path in ("/", "/healthz"):
        assert c.head(path).status_code == 200, path


def test_security_headers_on_pages_and_api():
    for r in (c.get("/"), c.get("/healthz"), c.post("/api/plan", json=SAMPLE), c.post("/api/plan", json={})):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_bad_favourite_type_gets_its_own_hint():
    body = {"travelers": [{"label": "A", "likes": [{"name": "Dune", "type": 123}]}]}
    r = c.post("/api/plan", json=body)
    assert r.status_code == 422 and "type" in r.json()["ask"] and "at least one favourite" not in r.json()["ask"]
    body["travelers"][0]["likes"][0]["type"] = "x" * 50
    assert c.post("/api/plan", json=body).status_code == 422


def test_unknown_type_name_falls_back_instead_of_failing():
    body = {"travelers": [{"label": "A", "likes": [{"name": "Dune", "type": "podcast"}]}]}
    assert c.post("/api/plan", json=body).status_code == 200


def test_thumbnail_fallback_does_not_put_names_in_inline_js():
    # A favourite starting with a quote (e.g. 'Allo 'Allo!) used to break the inline onerror handler.
    html = c.get("/").text
    assert "textContent:this.dataset.i" in html
    assert "textContent:'${initials(" not in html
