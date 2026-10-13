"""The service must START and stay correct on dirty exports (new problems at grading time)."""
import pytest
from helpers import make_dir, client

P = "P1,One,ORG03,Dev,Pune\nP2,Two,ORG03,Dev,Pune\n"
S = "P1,A,standard,2026-01-01,\nP2,A,standard,2026-01-01,\n"
PR = "A,standard,30\n"
Q = "/api/summary?from=2026-07-01&to=2026-07-31"


def run(monkeypatch, **kw):
    kw.setdefault("people", P); kw.setdefault("seats", S); kw.setdefault("prices", PR)
    with client(monkeypatch, make_dir(**kw)) as c:
        assert c.get("/health").status_code == 200
        return c.get(Q).json()


@pytest.mark.parametrize("ts", [
    "2026-07-02 10:00:00", "2026-07-02T10:00:00", "2026-07-02T10:00:00Z", "2026-07-02 10:00:00+05:30",
    "2026-07-02 10:00", "2026-07-02", "2026-07-02 10:00:00.250", "2026/07/02 10:00:00"])
def test_timestamp_formats_all_count(monkeypatch, ts):
    assert run(monkeypatch, events=f"P1,A,chat,{ts}\n")["active_users"] == 1


def test_case_and_whitespace_in_ids_and_tools(monkeypatch):
    assert run(monkeypatch, events="  p1 , a ,chat,2026-07-02 10:00:00\n")["active_users"] == 1


def test_duplicate_events_do_not_double_count(monkeypatch):
    assert run(monkeypatch, events="P1,A,chat,2026-07-02 10:00:00\n" * 5)["active_users"] == 1


def test_garbage_event_rows_are_skipped(monkeypatch):
    r = run(monkeypatch, events="\n,,,\nP1,A,chat,not-a-date\nP1,Z,chat,2026-07-02 10:00:00\nP1,A,chat,2026-07-03 09:00:00\n")
    assert r["active_users"] == 1


def test_duplicate_people_rows_do_not_crash(monkeypatch):
    assert run(monkeypatch, people=P + "P1,One,ORG03,Dev,Pune\n")["licensed_users"] == 2


def test_person_with_unknown_or_blank_org(monkeypatch):
    r = run(monkeypatch, people=P + "P3,Three,ORG99,Dev,Pune\nP4,Four,,Dev,Pune\n",
            seats=S + "P3,A,standard,2026-01-01,\n")
    assert r["licensed_users"] == 3  # still a Helix developer, counted company-wide



@pytest.mark.parametrize("raw,expected", [("$30", 62.0), ("30 USD", 62.0), ("30.00", 62.0), ("", 0.0), ("n/a", 0.0)])
def test_price_formats(monkeypatch, raw, expected):
    assert run(monkeypatch, prices=f'A,standard,"{raw}"\n')["spend"] == expected



def test_org_cycle_and_missing_parent_do_not_crash(monkeypatch):
    orgs = "ORG01,Eng,ORG02,L3\nORG02,Plat,ORG01,L4\nORG03,Team,ORG99,L6\n"
    r = run(monkeypatch, orgs=orgs)
    assert r["licensed_users"] == 2
