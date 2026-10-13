"""Policy tests. All ids/counts are generated here; nothing depends on the shipped data folder."""
import random
from datetime import date, timedelta
import pytest
from helpers import make_dir, client

P = "P1,One,ORG03,Dev,Pune\nP2,Two,ORG03,Dev,Pune\n"
S = "P1,A,standard,2026-01-01,\nP2,A,standard,2026-01-01,\n"
Q = "/api/summary?from=2026-07-01&to=2026-07-31"


def get(monkeypatch, path=Q, **kw):
    kw.setdefault("people", P); kw.setdefault("seats", S); kw.setdefault("prices", "A,standard,30\n")
    with client(monkeypatch, make_dir(**kw)) as c:
        assert c.get("/health").status_code == 200
        return c.get(path).json()


# ---- duplicate prices
def test_identical_price_rows_are_deduplicated(monkeypatch):
    assert get(monkeypatch, prices="A,standard,30\nA,standard,30\n")["spend"] == 62.0


@pytest.mark.parametrize("rows", ["A,standard,20\nA,standard,30\n", "A,standard,30\nA,standard,20\n", "A,standard,30\nA,standard,\n"])
def test_conflicting_price_is_unpriced_whatever_the_file_order(monkeypatch, rows):
    r = get(monkeypatch, prices=rows)
    assert r["spend"] == 0.0 and r["idle_spend"] == 0.0 and r["licensed_users"] == 2
    with client(monkeypatch, make_dir(P, seats=S, prices=rows)) as c:
        a = c.get("/api/tools?from=2026-07-01&to=2026-07-31").json()[0]
        assert (a["spend"], a["idle_spend"], a["cost_per_active"]) == (None, None, None)


def test_conflict_in_one_tier_does_not_poison_another_tier(monkeypatch):
    r = get(monkeypatch, seats="P1,A,standard,2026-01-01,\nP2,A,pro,2026-01-01,\n",
            prices="A,standard,30\nA,pro,10\nA,pro,99\n")
    assert r["spend"] == 31.0  # only P1's standard seat is priced (30 * 31 / 30)


# ---- duplicate seats
def test_identical_seat_rows_are_deduplicated(monkeypatch):
    r = get(monkeypatch, seats=S + S)
    assert (r["licensed_users"], r["spend"]) == (2, 62.0)


@pytest.mark.parametrize("extra", ["P1,A,standard,2026-02-01,2026-03-01\n", "P1,A,pro,2026-01-01,\n", "P1,A,standard,2026-01-01,2026-09-01\n"])
def test_conflicting_seat_rows_quarantine_that_person_tool_only(monkeypatch, extra):
    r = get(monkeypatch, seats=S + extra, prices="A,standard,30\nA,pro,60\n",
            events="P1,A,chat,2026-07-02 10:00:00\nP2,A,chat,2026-07-02 10:00:00\n")
    assert (r["licensed_users"], r["active_users"], r["spend"]) == (1, 1, 31.0)  # only P2 remains, P1's usage has no seat


def test_conflicting_seat_in_one_tool_keeps_the_other_tool(monkeypatch):
    r = get(monkeypatch, seats=S + "P1,A,standard,2026-02-01,2026-03-01\nP1,B,standard,2026-01-01,\n",
            prices="A,standard,30\nB,standard,30\n")
    assert r["licensed_users"] == 2 and r["spend"] == 62.0  # P2/A (31) + P1/B (31); P1/A is quarantined


# ---- duplicate people / orgs
def test_conflicting_person_org_means_company_wide_only(monkeypatch):
    p = P + "P1,One,ORG02,Dev,Pune\n"
    assert get(monkeypatch, people=p)["licensed_users"] == 2
    assert get(monkeypatch, "/api/summary?from=2026-07-01&to=2026-07-31&org=ORG03", people=p)["licensed_users"] == 1


def test_identical_person_rows_are_deduplicated(monkeypatch):
    assert get(monkeypatch, "/api/summary?from=2026-07-01&to=2026-07-31&org=ORG03", people=P + P)["licensed_users"] == 2


# ---- events: every type counts, only on a day a matching seat was held
@pytest.mark.parametrize("etype", ["chat", "completion", "agent", "", "something_new"])
def test_every_event_type_is_usage(monkeypatch, etype):
    assert get(monkeypatch, events=f"P1,A,{etype},2026-07-02 10:00:00\n")["active_users"] == 1


def test_active_users_counts_people_not_events(monkeypatch):
    ev = "".join(f"P1,A,{t},2026-07-{d:02d} 1{d % 10}:00:00\n" for d in range(1, 20) for t in ("chat", "agent"))
    assert get(monkeypatch, events=ev)["active_users"] == 1


@pytest.mark.parametrize("seat,event,counts", [
    ("2026-07-10,", "2026-07-09 23:59:59", 0), ("2026-07-10,", "2026-07-10 00:00:00", 1),
    ("2026-01-01,2026-07-10", "2026-07-09 23:59:59", 1), ("2026-01-01,2026-07-10", "2026-07-10 00:00:00", 0),
    ("2026-01-01,2026-07-10", "2026-07-10 12:00:00", 0)])
def test_event_must_fall_on_a_day_the_seat_was_held(monkeypatch, seat, event, counts):
    r = get(monkeypatch, people="P1,One,ORG03,Dev,Pune\n", seats=f"P1,A,standard,{seat}\n", events=f"P1,A,chat,{event}\n")
    assert r["active_users"] == counts


def test_event_for_a_different_tool_than_the_seat_does_not_count(monkeypatch):
    r = get(monkeypatch, people="P1,One,ORG03,Dev,Pune\n", seats="P1,A,standard,2026-01-01,\n", events="P1,B,chat,2026-07-02 10:00:00\n")
    assert r["active_users"] == 0 and r["idle_spend"] == r["spend"] == 31.0


def test_event_in_window_but_seat_outside_window_is_not_licensed(monkeypatch):
    r = get(monkeypatch, people="P1,One,ORG03,Dev,Pune\n", seats="P1,A,standard,2026-01-01,2026-06-01\n", events="P1,A,chat,2026-07-02 10:00:00\n")
    assert (r["licensed_users"], r["active_users"], r["spend"]) == (0, 0, 0.0)


# ---- invariance: noise that carries no information must not change a single number
def _dataset(rnd, n=60):
    users = [f"X{i:04d}" for i in range(n)]
    seats, events = [], []
    for u in users:
        for tool in rnd.sample("ABCD", rnd.randint(1, 3)):
            g = date(2026, 1, 1) + timedelta(rnd.randint(0, 200))
            rv = g + timedelta(rnd.randint(0, 100)) if rnd.random() < .4 else None
            seats.append(f"{u},{tool},standard,{g},{rv or ''}")
            events += [f"{u},{tool},{rnd.choice(['chat', 'agent', 'completion'])},{date(2026, 1, 1) + timedelta(rnd.randint(0, 320))} 1{rnd.randint(0, 9)}:{rnd.randint(10, 59)}:00"
                       for _ in range(rnd.randint(0, 5))]
    return users, seats, events


def test_noise_does_not_change_results(monkeypatch):
    rnd = random.Random(5)
    users, seats, events = _dataset(rnd)
    people = [f"{u},N,ORG03,Dev,Pune" for u in users]
    prices = ["A,standard,19", "B,standard,25.5", "C,standard,30", "D,standard,"]
    clean = make_dir("\n".join(people) + "\n", seats="\n".join(seats) + "\n", prices="\n".join(prices) + "\n", events="\n".join(events) + "\n")
    noisy_events = [e.replace(" ", "T") if rnd.random() < .3 else e for e in events]            # ISO 'T'
    noisy_events += rnd.sample(events, 40) * 2                                                  # exact duplicates
    noisy_events += [f"GHOST{i},A,chat,2026-07-05 10:00:00" for i in range(25)]                 # not Helix developers
    noisy_events += ["", ",,,", "X0001,A,chat,garbage", "X0001,Q,chat,2026-07-05 10:00:00"]     # junk rows
    noisy_events = [f" {e.split(',')[0].lower()} ,{e.split(',', 1)[1]}" if e.count(',') == 3 and rnd.random() < .2 else e for e in noisy_events]  # case + spaces
    rnd.shuffle(noisy_events)
    noisy = make_dir("\n".join(people + people[:10]) + "\n\n", seats="\n".join(seats + seats[:30]) + "\n",
                     prices="\n".join(prices + prices[:2]) + "\n", events="\n".join(noisy_events) + "\n")
    paths = [f"/api/{ep}?from={a}&to={b}" for ep in ("summary", "tools")
             for a, b in (("2026-03-01", "2026-03-31"), ("2026-07-01", "2026-09-30"), ("2026-01-01", "2026-12-31"), ("2026-05-05", "2026-05-05"))]
    with client(monkeypatch, clean) as c1:
        want = [c1.get(p).json() for p in paths]
    with client(monkeypatch, noisy) as c2:
        got = [c2.get(p).json() for p in paths]
    assert got == want
