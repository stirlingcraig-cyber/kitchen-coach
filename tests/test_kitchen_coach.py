"""Tests for the recipe parser and the local web engine.  Run:  python -m pytest -q"""
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import recipe_parser as rp  # noqa: E402
from app import Presence, create_app  # noqa: E402

SAMPLES = ROOT / "tests" / "samples"
CASES = json.loads((ROOT / "tests" / "fixtures" / "cases.json").read_text(encoding="utf-8"))


def parse(name):
    return rp.parse_recipe(name, (SAMPLES / name).read_bytes())


# ---------------------------------------------------------------- samples
@pytest.mark.parametrize("name,title,steps,first_timer", [
    ("beef_ragu.pdf", "Slow-Cooked Beef Ragu", 7, 300),
    ("lemon_drizzle.docx", "Lemon Drizzle Cake", 6, 0),
    ("pancakes.xhtml", "Fluffy American Pancakes", 5, 0),
    ("tray_bake.html", "Easy Chicken Tray Bake", 5, 0),
    ("risotto.xml", "Mushroom Risotto", 5, 300),
    ("boiled_eggs.txt", "Perfect Soft-Boiled Eggs", 3, 0),
])
def test_samples(name, title, steps, first_timer):
    r = parse(name)
    assert r["title"] == title
    assert len(r["steps"]) == steps
    assert r["steps"][0]["seconds"] == first_timer
    assert r["ingredients"], "ingredients should be found"


def test_pdf_wrapped_lines_are_rejoined():
    texts = [s["text"] for s in parse("beef_ragu.pdf")["steps"]]
    assert "Meanwhile, cook the pappardelle in salted boiling water for 8-10 minutes, then drain." in texts


def test_word_auto_numbering_is_detected():
    r = parse("lemon_drizzle.docx")
    assert r["steps"][3]["seconds"] == 45 * 60
    assert not r["warnings"]


def test_inline_html_does_not_split_steps():
    step = parse("pancakes.xhtml")["steps"][1]["text"]
    assert step.endswith("Leave the batter to rest for 10 minutes.")


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_fixture_regression(case):
    assert rp.analyse(case["lines"], case["title_hint"], case["stem"], case["structured"]) == case["expected"]


# ---------------------------------------------------------------- durations
@pytest.mark.parametrize("text,seconds", [
    ("bake for 25 minutes", 1500), ("simmer 1 hour 30 minutes", 5400), ("half an hour", 1800),
    ("1½ hours", 5400), ("1 1/2 hours", 5400), ("2 hrs 15 mins", 8100), ("1h30", 5400),
    ("45 secs", 45), ("20-25 minutes", 1200), ("twenty minutes", 1200), ("an hour", 3600),
    ("6 minutes and 30 seconds", 390),
])
def test_durations(text, seconds):
    assert rp.timer_for(text)[0] == seconds


@pytest.mark.parametrize("text", ["stir every 5 minutes", "Preheat to 180C", "a high heat", "1.5 kg beef"])
def test_not_durations(text):
    assert rp.timer_for(text)[0] == 0


def test_original_bug_decimal_ingredient_not_a_step():
    r = rp.analyse(["Stew", "1.5 kg beef", "1. Brown the beef.", "2. Simmer for 2 hours."])
    assert [s["text"] for s in r["steps"]] == ["Brown the beef.", "Simmer for 2 hours."]


def test_timer_is_capped_at_24_hours():
    assert rp.timer_for("Cure for 30 hours")[0] == 24 * 3600


# ---------------------------------------------------------------- errors & safety
def test_doc_file_rejected_helpfully():
    with pytest.raises(rp.RecipeError, match="Save As"):
        rp.parse_recipe("old.doc", b"x")


def test_unsupported_type():
    with pytest.raises(rp.RecipeError, match="Please upload"):
        rp.parse_recipe("photo.jpg", b"x")


def test_empty_file():
    with pytest.raises(rp.RecipeError, match="empty"):
        rp.parse_recipe("r.pdf", b"")


def test_xml_entity_attack_blocked():
    evil = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaa"><!ENTITY b "&a;&a;&a;">]><r>&b;</r>'
    with pytest.raises(rp.RecipeError):
        rp.parse_recipe("evil.xml", evil)


def test_xml_external_entity_blocked():
    evil = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r><step>&x;</step></r>'
    with pytest.raises(rp.RecipeError):
        rp.parse_recipe("evil.xml", evil)


def test_broken_xml():
    with pytest.raises(rp.RecipeError, match="isn't valid XML"):
        rp.parse_recipe("bad.xml", b"<recipe><step>oops</recipe>")


def test_broken_docx():
    with pytest.raises(rp.RecipeError, match="couldn't be opened"):
        rp.parse_recipe("bad.docx", b"not a zip")


def test_broken_pdf():
    with pytest.raises(rp.RecipeError):
        rp.parse_recipe("bad.pdf", b"%PDF-1.4 rubbish")


def test_scanned_pdf_without_text():
    from pypdf import PdfWriter
    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    w.write(buf)
    with pytest.raises(rp.RecipeError, match="scanned"):
        rp.parse_recipe("scan.pdf", buf.getvalue())


def test_encrypted_pdf():
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for page in PdfReader(SAMPLES / "beef_ragu.pdf").pages:
        w.add_page(page)
    w.encrypt("secret")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(rp.RecipeError, match="password"):
        rp.parse_recipe("locked.pdf", buf.getvalue())


def test_docx_table_recipe():
    from docx import Document
    d = Document()
    d.add_paragraph("Table Toast")
    d.add_paragraph("Method")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "1", "Toast the bread for 2 minutes."
    t.cell(1, 0).text, t.cell(1, 1).text = "2", "Butter and serve."
    buf = io.BytesIO()
    d.save(buf)
    r = rp.parse_recipe("toast.docx", buf.getvalue())
    assert [s["seconds"] for s in r["steps"]] == [120, 0]


# ---------------------------------------------------------------- web engine
@pytest.fixture()
def client():
    app = create_app()
    app.testing = True
    return app.test_client()


def test_health(client):
    assert client.get("/api/health").get_json()["app"] == "kitchen-coach"


def test_index_and_js_mime(client):
    assert b"Kitchen Coach" in client.get("/").data
    assert client.get("/app.js").mimetype == "text/javascript"
    assert client.get("/vendor/pdf.min.js").mimetype == "text/javascript"


def test_parse_endpoint(client):
    data = {"recipe": (io.BytesIO((SAMPLES / "risotto.xml").read_bytes()), "risotto.xml")}
    r = client.post("/api/parse", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["title"] == "Mushroom Risotto"


def test_parse_endpoint_friendly_error(client):
    data = {"recipe": (io.BytesIO(b"x"), "old.doc")}
    r = client.post("/api/parse", data=data, content_type="multipart/form-data")
    assert r.status_code == 422 and "Save As" in r.get_json()["error"]


def test_parse_missing_file(client):
    assert client.post("/api/parse", data={}, content_type="multipart/form-data").status_code == 400


def test_upload_too_large(client):
    data = {"recipe": (io.BytesIO(b"0" * (16 * 1024 * 1024)), "big.txt")}
    r = client.post("/api/parse", data=data, content_type="multipart/form-data")
    assert r.status_code == 413


def test_path_traversal_blocked(client):
    assert client.get("/../app.py").status_code in (403, 404) or b"def create_app" not in client.get("/../app.py").data
    assert b"def create_app" not in client.get("/%2e%2e/app.py").data


def test_foreign_host_blocked(client):
    assert client.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 403


def test_presence_shutdown_rules():
    p = Presence()
    assert not p.should_exit(now=p.started + 60)
    assert p.should_exit(now=p.started + 121)          # window never connected
    p.seen()
    assert not p.should_exit(now=p.last_seen + 100)
    assert p.should_exit(now=p.last_seen + 181)        # window gone quiet
    p.bye()
    assert p.should_exit(now=p.bye_at + 21)            # window closed
    p.seen()
    assert not p.should_exit(now=p.last_seen + 21)     # page was only reloaded
