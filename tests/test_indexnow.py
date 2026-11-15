"""IndexNow (scripts/indexnow.py): changed pages are listed at each build and reported to search
engines after the public site is published; the list empties only once they're accepted."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("indexnow", ROOT / "scripts" / "indexnow.py")
ix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ix)

KEY = "0123456789abcdef0123456789abcdef"


def test_nothing_happens_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("INDEXNOW_KEY", raising=False)
    monkeypatch.setattr(ix, "key", lambda: None)
    assert not ix.write_keyfile(tmp_path) and not list(tmp_path.iterdir())
    ix.add_pending(["about.html"], tmp_path / "p.json")
    assert ix.send(post=lambda b: 1 / 0, path=tmp_path / "p.json", log=lambda *_: None) == 0


def test_key_file_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(ix, "key", lambda: KEY)
    monkeypatch.setattr(ix, "site_url", lambda: "https://uscongressvsvoters.org")
    assert ix.write_keyfile(tmp_path) and (tmp_path / f"{KEY}.txt").read_text() == KEY
    pending = tmp_path / "p.json"
    ix.add_pending(["members/ted-cruz/", ""], pending)
    ix.add_pending(["members/ted-cruz/", "history/"], pending)          # builds add up, no repeats
    assert json.loads(pending.read_text()) == ["", "history/", "members/ted-cruz/"]

    refused = []
    assert ix.send(post=lambda b: refused.append(b) or 403, path=pending, log=lambda *_: None) == 0
    assert len(json.loads(pending.read_text())) == 3                     # kept for next time

    sent = []
    assert ix.send(post=lambda b: sent.append(b) or 202, path=pending, log=lambda *_: None) == 3
    body = sent[0]
    assert body["host"] == "uscongressvsvoters.org" and body["key"] == KEY
    assert body["keyLocation"] == f"https://uscongressvsvoters.org/{KEY}.txt"
    assert body["urlList"] == ["https://uscongressvsvoters.org/", "https://uscongressvsvoters.org/history/",
                               "https://uscongressvsvoters.org/members/ted-cruz/"]
    assert json.loads(pending.read_text()) == []


def test_a_build_lists_only_pages_that_changed(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    import test_profiles as tp
    from datetime import date
    out, record = tmp_path / "out", tmp_path / "state" / "page_lastmod.json"
    out.mkdir()
    (out / "about.html").write_text("x")
    (out / "index.html").write_text("x")
    tp.bp.build(out, tp.fake_api, "v1", today=date(2026, 11, 10), images=False, log=lambda *_: None, record=record)
    pending = record.parent / "indexnow_pending.json"
    first = json.loads(pending.read_text())
    assert "members/ted-cruz/" in first and "about.html" in first
    pending.write_text("[]")                                                # as if reported
    (out / "about.html").write_text("changed")
    tp.bp.build(out, tp.fake_api, "v2", today=date(2026, 11, 20), images=False, log=lambda *_: None, record=record)
    assert json.loads(pending.read_text()) == ["about.html"]
