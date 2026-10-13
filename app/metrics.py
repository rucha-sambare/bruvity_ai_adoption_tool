"""Metric calculation (Appendix P). Everything works on integer day ordinals,
so extreme dates (year 0001 / 9999) can never overflow."""
from __future__ import annotations

from bisect import bisect_left
from decimal import ROUND_HALF_UP, Decimal

from .loader import TOOLS

CENT, TENTH, ZERO = Decimal("0.01"), Decimal("0.1"), Decimal("0")


def money(v: Decimal) -> float:
    return float(v.quantize(CENT, rounding=ROUND_HALF_UP))


def pct(active: int, licensed: int) -> float:
    if licensed == 0:
        return 0.0
    return float((Decimal(active) * 100 / Decimal(licensed)).quantize(TENTH, rounding=ROUND_HALF_UP))


def users_in_scope(data: dict, org: str | None) -> set[str]:
    if org is None:
        return set(data["people"])
    orgs = data["descendants"][org]
    return {u for u, o in data["people"].items() if o in orgs}


def calculate(data: dict, start: int, end: int, scope: set[str]):
    """start/end are inclusive day ordinals. Returns (summary, per_tool_rows)."""
    prices, event_days = data["prices"], data["event_days"]
    priced_tool = {t: any(p is not None for (pt, _), p in prices.items() if pt == t) for t in TOOLS}

    lic = {t: set() for t in TOOLS}
    act = {t: set() for t in TOOLS}
    spend = {t: ZERO for t in TOOLS}
    idle = {t: ZERO for t in TOOLS}

    for s in data["seats"]:
        if s["user_id"] not in scope:
            continue
        first = max(s["start"], start)              # first held day inside window
        last = min(s["end"] - 1, end)               # revoked_on is the first day WITHOUT the seat
        if last < first:
            continue
        days_held, uid, tool = last - first + 1, s["user_id"], s["tool"]
        lic[tool].add(uid)
        days = event_days.get((uid, tool), ())
        i = bisect_left(days, first)
        used = i < len(days) and days[i] <= last    # any usage on a day the seat was held
        if used:
            act[tool].add(uid)
        price = prices.get((tool, s["tier"]))
        if price is None:
            continue                                # unpriced seat: left out of spend
        amount = price * days_held / Decimal(30)
        spend[tool] += amount
        if not used:
            idle[tool] += amount

    all_lic = set().union(*lic.values())
    all_act = set().union(*act.values())
    summary = {
        "licensed_users": len(all_lic),
        "active_users": len(all_act),
        "engagement_pct": pct(len(all_act), len(all_lic)),
        "spend": money(sum(spend.values(), ZERO)),
        "idle_spend": money(sum(idle.values(), ZERO)),
    }
    rows = []
    for t in TOOLS:
        l, a = len(lic[t]), len(act[t])
        priced = priced_tool[t]
        rows.append({
            "tool": t, "licensed_users": l, "active_users": a, "engagement_pct": pct(a, l),
            "spend": money(spend[t]) if priced else None,
            "idle_spend": money(idle[t]) if priced else None,
            "cost_per_active": money(spend[t] / a) if priced and a else None,
        })
    return summary, rows
