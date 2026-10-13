"""Appendix P worked example, plus window-edge rules."""
from helpers import make_dir, client

PEOPLE = "P1,One,ORG03,Dev,Pune\nP2,Two,ORG03,Dev,Pune\n"
PRICES = "A,standard,19\nC,standard,30\n"
SEATS = "P1,A,standard,2026-03-01,\nP1,C,standard,2026-07-21,\nP2,A,standard,2026-03-01,2026-07-16\n"
EVENTS = "P1,A,chat,2026-07-10 10:00:00\n"


def test_worked_example(monkeypatch):
    with client(monkeypatch, make_dir(PEOPLE, seats=SEATS, prices=PRICES, events=EVENTS)) as c:
        r = c.get("/api/summary?from=2026-07-01&to=2026-07-30")
        assert r.json() == {"licensed_users": 2, "active_users": 1, "engagement_pct": 50.0,
                            "spend": 38.5, "idle_spend": 19.5}


def test_revoked_on_is_first_day_without_seat(monkeypatch):
    # seat revoked 2026-07-16: usage on the 16th must NOT count, usage on the 15th must.
    seats = "P1,A,standard,2026-01-01,2026-07-16\n"
    for day, active in (("2026-07-15", 1), ("2026-07-16", 0)):
        with client(monkeypatch, make_dir("P1,One,ORG03,Dev,Pune\n", seats=seats, prices="A,standard,30\n",
                                          events=f"P1,A,chat,{day} 23:59:59\n")) as c:
            assert c.get("/api/summary?from=2026-07-01&to=2026-07-31").json()["active_users"] == active


def test_usage_before_grant_does_not_count(monkeypatch):
    with client(monkeypatch, make_dir("P1,One,ORG03,Dev,Pune\n", seats="P1,A,standard,2026-07-20,\n",
                                      prices="A,standard,30\n", events="P1,A,chat,2026-07-19 10:00:00\n")) as c:
        s = c.get("/api/summary?from=2026-07-01&to=2026-07-31").json()
        assert (s["licensed_users"], s["active_users"], s["spend"], s["idle_spend"]) == (1, 0, 12.0, 12.0)


def test_unpriced_tool_is_null_and_excluded(monkeypatch):
    with client(monkeypatch, make_dir("P1,One,ORG03,Dev,Pune\n", seats="P1,E,standard,2026-01-01,\n",
                                      prices="E,standard,\n", events="P1,E,chat,2026-07-02 10:00:00\n")) as c:
        s = c.get("/api/summary?from=2026-07-01&to=2026-07-31").json()
        assert s["spend"] == 0.0 and s["active_users"] == 1
        e = c.get("/api/tools?from=2026-07-01&to=2026-07-31").json()[4]
        assert (e["tool"], e["spend"], e["idle_spend"], e["cost_per_active"]) == ("E", None, None, None)


def test_tools_returns_five_rows_in_order(monkeypatch):
    with client(monkeypatch, make_dir("P1,One,ORG03,Dev,Pune\n", seats="P1,A,standard,2026-01-01,\n", prices="A,standard,19\n")) as c:
        rows = c.get("/api/tools?from=2026-07-01&to=2026-07-31").json()
        assert [r["tool"] for r in rows] == list("ABCDE")


def test_people_not_in_people_csv_are_ignored_and_org_rollup(monkeypatch):
    people = "P1,One,ORG03,Dev,Pune\n"
    seats = "P1,A,standard,2026-01-01,\nGHOST,A,standard,2026-01-01,\n"
    events = "P1,A,chat,2026-07-02 10:00:00\nGHOST,A,chat,2026-07-02 10:00:00\n"
    with client(monkeypatch, make_dir(people, seats=seats, prices="A,standard,30\n", events=events)) as c:
        for org in ("", "&org=ORG01", "&org=ORG02", "&org=ORG03"):  # roll-up through parents
            assert c.get(f"/api/summary?from=2026-07-01&to=2026-07-31{org}").json()["licensed_users"] == 1
