"""Cross-check against a deliberately naive day-by-day implementation on random data."""
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from helpers import make_dir, client

PRICES = {("A", "standard"): 19, ("A", "pro"): 39, ("B", "standard"): 25, ("C", "standard"): 30, ("C", "enterprise"): 60, ("D", "standard"): 20}


def naive(people, seats, events, frm, to):
    days = [frm + timedelta(i) for i in range((to - frm).days + 1)]
    lic, act, spend, idle = set(), set(), Decimal(0), Decimal(0)
    for uid, tool, tier, g, rv in seats:
        held = [d for d in days if g <= d and (rv is None or d < rv)]
        if not held:
            continue
        lic.add(uid)
        used = any((uid, tool, d) in events for d in held)
        if used:
            act.add(uid)
        p = PRICES.get((tool, tier))
        if p is not None:
            amt = Decimal(p) * len(held) / 30
            spend += amt
            idle += 0 if used else amt
    q = lambda v, n: float(Decimal(v).quantize(Decimal(n), rounding=ROUND_HALF_UP))
    e = q(Decimal(len(act)) * 100 / len(lic), "0.1") if lic else 0.0
    return dict(licensed_users=len(lic), active_users=len(act), engagement_pct=e, spend=q(spend, "0.01"), idle_spend=q(idle, "0.01"))


def test_random_windows_match_naive(monkeypatch):
    rnd = random.Random(42)
    users = [f"U{i:03d}" for i in range(40)]
    seats, ev_rows, evset = [], [], set()
    for u in users:
        for tool in rnd.sample("ABCD", rnd.randint(1, 3)):
            tier = rnd.choice([t for (tt, t) in PRICES if tt == tool])
            g = date(2026, 1, 1) + timedelta(rnd.randint(0, 200))
            rv = g + timedelta(rnd.randint(0, 120)) if rnd.random() < 0.4 else None
            seats.append((u, tool, tier, g, rv))
            for _ in range(rnd.randint(0, 6)):
                d = date(2026, 1, 1) + timedelta(rnd.randint(0, 330))
                ev_rows.append(f"{u},{tool},chat,{d} 10:00:00"); evset.add((u, tool, d))
    d = make_dir("".join(f"{u},N,ORG03,Dev,Pune\n" for u in users),
                 seats="".join(f"{u},{t},{ti},{g},{rv or ''}\n" for u, t, ti, g, rv in seats),
                 prices="".join(f"{t},{ti},{p}\n" for (t, ti), p in PRICES.items()), events="\n".join(ev_rows) + "\n")
    with client(monkeypatch, d) as c:
        for _ in range(60):
            a = date(2026, 1, 1) + timedelta(rnd.randint(0, 300)); b = a + timedelta(rnd.randint(0, 90))
            got = c.get(f"/api/summary?from={a}&to={b}").json()
            assert got == naive(users, seats, evset, a, b), (a, b)
