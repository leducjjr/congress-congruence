"""The Surveyed votes page's API: every question, and one question's members against their areas."""

import os

from test_ppc import conn, test_load_and_compare  # noqa: F401  (database fixture and demo data)


def client_for(monkeypatch):
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    return TestClient(api.app)


def test_list_has_every_linked_question_with_its_votes(conn, monkeypatch):  # noqa: F811
    test_load_and_compare(conn, monkeypatch, None)
    with client_for(monkeypatch) as client:
        qs = client.get("/v1/surveyed", params={"member": "A000001"}).json()["questions"]
    assert sorted(x["item"] for x in qs) == ["ACA", "REL", "UKR"]
    ukr = next(x for x in qs if x["item"] == "UKR")
    (v,) = ukr["votes"]
    assert v["members"]["with_majority"] == 1 and v["members"]["against_majority"] == 1
    assert v["your_members"][0]["bioguide_id"] == "A000001"
    assert ukr["spread"]["districts"]["areas"] == 2


def test_detail_places_every_member_against_their_own_area(conn, monkeypatch):  # noqa: F811
    test_load_and_compare(conn, monkeypatch, None)
    with client_for(monkeypatch) as client:
        d = client.get("/v1/surveyed/detail", params={"survey": "PPC 2026", "item": "UKR"}).json()
        missing = client.get("/v1/surveyed/detail", params={"survey": "PPC 2026", "item": "NOPE"})
    assert missing.status_code == 404
    assert d["question"] == "Aid Ukraine"
    (v,) = d["votes"]
    members = {m["bioguide_id"]: m for m in v["member_votes"]}
    a, b = members["A000001"], members["B000001"]
    # A voted Nay on an amendment to block aid: on the support side, with a 70% majority in IA-1.
    assert (a["position"], a["sided_with"], a["agreement"]) == ("nay", "support", "with")
    assert a["seat"] == "IA-1" and a["area"]["support_pct"] == 70.0 and a["area"]["majority"] == "support"
    assert (b["sided_with"], b["agreement"]) == ("oppose", "against")
