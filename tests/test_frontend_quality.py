"""Accessibility, mobile and load-speed guarantees of the single-page UI (no browser needed)."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
HTML = (Path(__file__).parent.parent / "app" / "static" / "index.html").read_text(encoding="utf-8")


def _qimg():
    m = re.search(r"const qimg=\(u,w\)=>u\.replace\(/(.+?)/i,'\$1'\+w\+'x-auto\$2'\)", HTML)
    assert m, "qimg helper missing"
    rx = re.compile(m.group(1).replace("\\/", "/"), re.I)
    return lambda u, w: rx.sub(lambda g: f"{g.group(1)}{w}x-auto{g.group(2)}", u)


def test_page_is_edge_cacheable_and_compressed():
    for r in (c.get("/"), c.head("/")):
        cc = r.headers["cache-control"]
        assert "s-maxage=" in cc and "max-age=0" in cc
    r = c.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert "no-store" not in c.get("/healthz").headers.get("cache-control", "")


def test_qloo_images_are_requested_at_the_drawn_size():
    q = _qimg()
    u = "https://images.qloo.com/i/35D9EDC3-DC6A-42A5-B73B-7A18DCF0C024-420x-auto.jpg"
    assert q(u, 64).endswith("-64x-auto.jpg")
    assert q(u.replace(".jpg", ".png"), 300).endswith("-300x-auto.png")
    for other in ("https://example.com/a-420x-auto.jpg", "https://images.qloo.com/i/abc.jpg",
                  "https://images.qloo.com/i/X-420x-auto.jpg?v=1"):
        assert q(other, 64) == other
    assert "qimg(m.image,64)" in HTML and 'srcset="${esc(qimg(x.image,300))} 300w' in HTML
    assert 'decoding="async"' in HTML and 'loading="lazy"' in HTML


def test_failed_images_fall_back_to_a_readable_placeholder():
    assert "onerror=\"this.remove()\"" in HTML  # stop photo removed, placeholder underneath stays
    assert 'class="ph0" aria-hidden="true" style="color:${colT(x.for)}"' in HTML
    assert "replaceWith(Object.assign(document.createElement('i')" in HTML  # thumbnail -> initial
    assert ".img img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0" in HTML
    assert "onload=\"this.classList.add('ld')\"" in HTML
    assert all('alt=""' in tag for tag in re.findall(r"<img [^>]+>", HTML))  # names are printed next to them


def test_keyboard_focus_is_clearly_visible():
    assert ":focus-visible{outline:3px solid #7b61ff" in HTML
    assert "#a99cf0" not in HTML  # the old 2.4:1 lavender focus border
    ring = ".like select:focus-visible,.like input:focus,.opt input:focus{outline:none;border-color:var(--violet)"
    assert ring in HTML
    assert ".lbl:focus-visible{outline:none;box-shadow:0 0 0 2px var(--violet)" in HTML


def test_form_labels_and_screen_reader_text():
    for m in re.finditer(r"<label\b([^>]*)>", HTML):
        assert "for=" in m.group(1), m.group(0)
    assert 'role="group" aria-labelledby="dayslbl"' in HTML and 'id="dayslbl"' in HTML
    assert '<span class="sr">Own picks per traveler:' in HTML  # the colour bar itself is aria-hidden
    assert 'aria-live="polite"' in HTML and 'role="alert"' in HTML


def test_mobile_inputs_do_not_trigger_ios_zoom_and_targets_are_big_enough():
    mobile = re.search(r"@media\(max-width:640px\)\{(.+?)\}\s*</style>", HTML, re.S).group(1)
    assert ".like input,.like select,.opt input,.lbl{font-size:16px}" in mobile
    assert ".x{min-width:40px;min-height:40px}" in mobile
    assert "white-space:nowrap" in re.search(r"\.brand\{[^}]+\}", HTML).group(0)
    assert "@media(max-width:420px){.bl{display:none}}" in HTML


def test_reduced_motion_is_respected_in_css_and_js():
    assert "@media(prefers-reduced-motion:reduce)" in HTML
    assert "matchMedia('(prefers-reduced-motion: reduce)')" in HTML and "behavior:RM?'auto':'smooth'" in HTML


def test_no_render_blocking_third_party_assets():
    assert not re.search(r"<(script|link)[^>]+(src|href)=\"https?://", HTML)
    assert '<meta name="theme-color"' in HTML and 'property="og:title"' in HTML
