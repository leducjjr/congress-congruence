"""Bill subjects from Congress.gov (with a stand-in for the API), and searching by them."""

import os

import pytest

from congress_congruence.ingest import bills
from test_ppc import conn, test_load_and_compare  # noqa: F401  (database fixture and demo data)


class FakeResponse:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeCongressGov:
    """Answers like api.congress.gov: a bill, then its subjects in two pages."""
    def __init__(self, status=200):
        self.status, self.calls = status, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if self.status != 200:
            return FakeResponse(self.status)
        if url.endswith("/bill/119/hr/1834"):
            return FakeResponse(200, {"bill": {
                "title": "Lower Health Care Premiums for All Americans Act", "introducedDate": "2025-03-04",
                "policyArea": {"name": "Health"}, "updateDate": "2026-01-09",
                "latestAction": {"actionDate": "2026-01-08", "text": "Passed/agreed to in House."}}})
        if url.endswith("/bill/119/hr/1834/subjects"):
            return FakeResponse(200, {"subjects": {"legislativeSubjects": [{"name": "Health insurance"}],
                                                   "policyArea": {"name": "Health"}},
                                      "pagination": {"count": 2, "next": url + "?offset=1"}})
        if url.endswith("/subjects?offset=1"):
            return FakeResponse(200, {"subjects": {"legislativeSubjects": [{"name": "Tax credits"}]},
                                      "pagination": {"count": 2}})
        return FakeResponse(404)


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(bills, "PAUSE_SECONDS", 0)
    monkeypatch.setattr(bills.time, "sleep", lambda s: None)
    monkeypatch.setenv("CONGRESS_API_KEY", "test-key")


def test_fetch_bill_reads_title_policy_area_and_every_page_of_subjects():
    http = FakeCongressGov()
    data = bills.fetch_bill(http, "test-key", 119, "hr", 1834)
    assert data["policy_area"] == "Health" and data["subjects"] == ["Health insurance", "Tax credits"]
    assert data["bill"]["title"].startswith("Lower Health Care")
    assert all(p.get("api_key") == "test-key" for _, p in http.calls)
    assert bills.fetch_bill(http, "test-key", 119, "hr", 9999) == {}


def test_a_refused_key_stops_with_a_clear_message_that_hides_the_key():
    with pytest.raises(bills.KeyProblem) as e:
        bills.get_json(FakeCongressGov(status=403), f"{bills.API}/bill/119/hr/1", "secret-key")
    assert "secret-key" not in str(e.value) and "CONGRESS_API_KEY" in str(e.value)


def test_a_reply_cut_off_mid_way_is_retried():
    """2026-11-09: one dropped connection (ChunkedEncodingError) ended a whole nightly run."""
    class Flaky(FakeCongressGov):
        drops = 1
        def get(self, url, params=None, timeout=None):
            if self.drops:
                self.drops -= 1
                raise bills.requests.exceptions.ChunkedEncodingError("Response ended prematurely")
            return super().get(url, params, timeout)
    data = bills.fetch_bill(Flaky(), "test-key", 119, "hr", 1834)
    assert data["policy_area"] == "Health"


def test_missing_key(monkeypatch):
    monkeypatch.delenv("CONGRESS_API_KEY")
    with pytest.raises(bills.KeyProblem):
        bills.api_key()


def test_sync_stores_subjects_and_search_finds_votes_and_questions_by_them(conn, monkeypatch, tmp_path):  # noqa: F811
    test_load_and_compare(conn, monkeypatch, None)
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    with conn.cursor() as cur:   # the ACA vote is on H.R. 1834; titles don't mention insurance or tax credits
        cur.execute("update core.roll_call set bill_type = 'hr', bill_number = 1834, bill_congress = 119, "
                    "description = 'Breaking the Gridlock Act' where roll_call_id = 'h-119-2-11'")
    conn.commit()

    result = bills.sync(conn, http=FakeCongressGov())
    assert result["bills_checked"] == 1 and result["not_found"] == 0
    assert (tmp_path / "congress_gov" / "bills" / "119" / "hr1834.json").exists()
    with conn.cursor() as cur:
        cur.execute("select title, policy_area, checked_at is not null from core.bill")
        assert cur.fetchall() == [("Lower Health Care Premiums for All Americans Act", "Health", True)]
        cur.execute("select subject from core.bill_subject order by subject")
        assert [r[0] for r in cur.fetchall()] == ["Health insurance", "Tax credits"]
    assert bills.sync(conn, http=FakeCongressGov())["bills_checked"] == 0      # nothing new to check

    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    with TestClient(api.app) as client:
        found = client.get("/v1/search", params={"q": "tax credit*", "only": "text"}).json()
        by_topic = client.get("/v1/search", params={"q": "health", "only": "text"}).json()
    (vote,) = found["votes"]                                       # found through a subject tag
    assert vote["roll_call_id"] == "h-119-2-11" and vote["policy_area"] == "Health"
    assert "Tax credits" in vote["subjects"] and vote["bill_title"].startswith("Lower Health Care")
    assert vote["matched_by"] == "subject" and found["questions"] == []
    assert [q["item"] for q in by_topic["questions"]] == ["ACA"]   # the question, through its bill's topic


def test_big_bills_subject_lists_dont_drag_questions_in_and_title_matches_come_first(conn, monkeypatch, tmp_path):  # noqa: F811
    test_load_and_compare(conn, monkeypatch, None)
    with conn.cursor() as cur:
        # The Ukraine amendment vote is on a big defense bill tagged with many subjects, immigration among them.
        cur.execute("update core.roll_call set bill_type = 'hr', bill_number = 3838, bill_congress = 119, "
                    "description = 'Amendment on Ukraine' where roll_call_id = 'h-119-1-255'")
        cur.execute("update core.roll_call set description = 'Immigration Enforcement Act' where roll_call_id = 'h-119-2-11'")
        cur.execute("insert into core.bill (congress, bill_type, bill_number, title, policy_area) "
                    "values (119, 'hr', 3838, 'National Defense Authorization Act', 'Armed Forces and National Security')")
        cur.executemany("insert into core.bill_subject values (119, 'hr', 3838, %s)",
                        [("Immigration status and procedures",), ("Military procurement",)])
    conn.commit()
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    with TestClient(api.app) as client:
        found = client.get("/v1/search", params={"q": "immigration", "only": "text"}).json()
    assert found["questions"] == []                              # Ukraine question not pulled in by a tag
    assert [(v["roll_call_id"], v["matched_by"]) for v in found["votes"]] == \
        [("h-119-2-11", "title"), ("h-119-1-255", "subject")]   # title match first, though it's older-or-newer
