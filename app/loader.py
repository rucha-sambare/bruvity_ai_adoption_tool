"""Load and clean the five CSV exports.

Design rule: the loader NEVER stops the service because of dirty rows.
Every problem is handled by a fixed rule (normalise, drop, or pick one row),
and counted in a DataReport that is printed at start-up and described in DATA.md.
Only a missing file or a missing column is fatal, because no answer is possible then.
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

TOOLS = ("A", "B", "C", "D", "E")
REQUIRED = {
    "people.csv": {"user_id", "name", "org_unit_id", "role", "location"},
    "org_units.csv": {"org_unit_id", "name", "parent_id", "level"},
    "seats.csv": {"user_id", "tool", "tier", "granted_on", "revoked_on"},
    "price_list.csv": {"tool", "tier", "monthly_price_usd"},
    "activity_events.csv": {"user_id", "tool", "event_type", "event_ts"},
}
NO_END = 10 ** 9  # "never revoked" as a day ordinal (far beyond year 9999)


class DataError(ValueError):
    """A file or column is missing, so no correct answer is possible."""


@dataclass
class DataReport:
    counts: Counter = field(default_factory=Counter)
    examples: dict = field(default_factory=dict)

    def record(self, issue: str, detail: str = "", limit: int = 3) -> None:
        self.counts[issue] += 1
        ex = self.examples.setdefault(issue, [])
        if detail and len(ex) < limit:
            ex.append(detail)

    def summary_lines(self) -> list[str]:
        if not self.counts:
            return ["Data validation: no issues found."]
        lines = ["Data validation: issues handled by rule:"]
        for issue, n in sorted(self.counts.items()):
            lines.append(f"  - {issue}: {n}  e.g. {self.examples.get(issue, [])}")
        return lines


# ---------------------------------------------------------------- parsing helpers
_ISO_DAY = re.compile(r"^\s*(\d{4})[-/.]?(\d{2})[-/.]?(\d{2})(?:$|[T\s].*$)")


def parse_day(value: str) -> int | None:
    """Return a day ordinal from 'YYYY-MM-DD' (also YYYY/MM/DD, YYYYMMDD, or with a
    time / 'T' / zone suffix). The wall-clock date as written is used, because
    event_ts is local time. Ambiguous day-first/month-first formats return None."""
    m = _ISO_DAY.match(value or "")
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).toordinal()
    except ValueError:
        return None


def parse_price(value: str) -> Decimal | None:
    """Blank or non-numeric means 'not priced yet'. Tolerates $, USD, spaces, 1,234.50."""
    v = re.sub(r"(?i)usd|\$|\s", "", value or "")
    if not v:
        return None
    if v.count(",") >= 1 and "." not in v and re.fullmatch(r"\d{1,3}(,\d{3})+", v) is None:
        v = v.replace(",", ".")  # decimal comma, e.g. 19,5
    else:
        v = v.replace(",", "")
    try:
        d = Decimal(v)
    except InvalidOperation:
        return None
    return d if d.is_finite() and d >= 0 else None


def _read(path: Path, required: set[str]) -> list[dict]:
    if not path.exists():
        raise DataError(f"Required data file is missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        names = [(n or "").strip().lower() for n in (reader.fieldnames or [])]
        reader.fieldnames = names
        missing = required - set(names)
        if missing:
            raise DataError(f"{path.name} is missing columns: {sorted(missing)}")
        rows = []
        for raw in reader:
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            if any(row.values()):  # skip blank lines / ",,,"
                rows.append(row)
        return rows


# ---------------------------------------------------------------- main loader
def load_data(data_dir: Path) -> dict:
    rep = DataReport()
    people_raw = _read(data_dir / "people.csv", REQUIRED["people.csv"])
    org_raw = _read(data_dir / "org_units.csv", REQUIRED["org_units.csv"])
    seats_raw = _read(data_dir / "seats.csv", REQUIRED["seats.csv"])
    price_raw = _read(data_dir / "price_list.csv", REQUIRED["price_list.csv"])
    events_raw = _read(data_dir / "activity_events.csv", REQUIRED["activity_events.csv"])

    # Policy for conflicting duplicates (the brief does not say which row is right and
    # file order is not a reliable signal): identical rows are de-duplicated; if rows for the
    # same key disagree, that key is treated as AMBIGUOUS and reported, never guessed.

    # ---- org units: conflicting parents for the same id => parent unknown (treated as a root)
    parents: dict[str, set[str]] = {}
    for r in org_raw:
        oid = r["org_unit_id"]
        if not oid:
            rep.record("org_blank_id")
            continue
        parents.setdefault(oid, set()).add(r["parent_id"].upper())
    org_ci = {o.upper(): o for o in parents}
    orgs: dict[str, str] = {}
    for oid, ps in parents.items():
        if len(ps) > 1:
            rep.record("org_conflicting_parent_treated_as_root", oid)
            orgs[oid] = ""
        else:
            orgs[oid] = org_ci.get(next(iter(ps)), next(iter(ps)))
    children: dict[str, list[str]] = {o: [] for o in orgs}
    for oid, parent in orgs.items():
        if not parent:
            continue
        if parent not in orgs:
            rep.record("org_missing_parent_treated_as_root", f"{oid}->{parent}")
        elif parent == oid:
            rep.record("org_self_parent", oid)
        else:
            children[parent].append(oid)
    descendants: dict[str, set[str]] = {}
    for root in orgs:
        seen, stack = set(), [root]
        while stack:  # 'seen' makes cycles harmless
            cur = stack.pop()
            if cur not in seen:
                seen.add(cur)
                stack.extend(children[cur])
        descendants[root] = seen

    # ---- people: conflicting org for the same id => org unknown (company-wide only)
    person_orgs: dict[str, set[str]] = {}
    for r in people_raw:
        uid = r["user_id"].upper()
        if not uid:
            rep.record("person_blank_id")
            continue
        person_orgs.setdefault(uid, set()).add(r["org_unit_id"].upper())
    people: dict[str, str] = {}  # user_id -> org_unit_id ('' = in no org subtree)
    for uid, os_ in person_orgs.items():
        if len(os_) > 1:
            rep.record("person_conflicting_org", uid)
            people[uid] = ""
            continue
        org = org_ci.get(next(iter(os_)), "")
        if not org:
            rep.record("person_unknown_or_blank_org", uid)
        people[uid] = org

    # ---- prices: same key, different values => ambiguous => unpriced (None)
    price_values: dict[tuple[str, str], set] = {}
    for r in price_raw:
        key = (r["tool"].upper(), r["tier"].lower())
        if key[0] not in TOOLS:
            rep.record("price_unknown_tool", str(key))
            continue
        p = parse_price(r["monthly_price_usd"])
        if r["monthly_price_usd"] and p is None:
            rep.record("price_unparseable_treated_as_unpriced", r["monthly_price_usd"])
        price_values.setdefault(key, set()).add(p)
    prices: dict[tuple[str, str], Decimal | None] = {}
    for key, vals in price_values.items():
        if len(vals) > 1:
            rep.record("price_conflicting_treated_as_unpriced", str(key))
            prices[key] = None
        else:
            prices[key] = next(iter(vals))

    # ---- seats: one seat per (person, tool). Conflicting rows => whole key quarantined.
    seat_variants: dict[tuple[str, str], set[tuple]] = {}
    for r in seats_raw:
        uid, tool, tier = r["user_id"].upper(), r["tool"].upper(), r["tier"].lower()
        if uid not in people:
            rep.record("seat_unknown_user", uid)
            continue
        if tool not in TOOLS:
            rep.record("seat_unknown_tool", tool)
            continue
        g = parse_day(r["granted_on"])
        rv = parse_day(r["revoked_on"]) if r["revoked_on"] else NO_END
        if g is None or rv is None:
            rep.record("seat_bad_date", f"{uid}/{tool}")
            continue
        if rv < g:
            rep.record("seat_revoked_before_granted", f"{uid}/{tool}")
            continue
        seat_variants.setdefault((uid, tool), set()).add((tier, g, rv))
    seats: list[dict] = []
    for (uid, tool), variants in seat_variants.items():
        if len(variants) > 1:
            rep.record("seat_conflicting_rows_quarantined", f"{uid}/{tool}")
            continue
        tier, g, rv = next(iter(variants))
        if (tool, tier) not in prices:
            rep.record("seat_tier_not_in_price_list", f"{tool}/{tier}")
        seats.append({"user_id": uid, "tool": tool, "tier": tier, "start": g, "end": rv})

    # ---- events: every event type is usage; reduced to distinct local days per (person, tool)
    event_days: dict[tuple[str, str], set[int]] = {}
    n_events = 0
    for r in events_raw:
        uid, tool = r["user_id"].upper(), r["tool"].upper()
        if uid not in people:
            rep.record("event_unknown_user_ignored", uid)
            continue
        if tool not in TOOLS:
            rep.record("event_unknown_tool", tool)
            continue
        day = parse_day(r["event_ts"])
        if day is None:
            rep.record("event_bad_timestamp", r["event_ts"])
            continue
        n_events += 1
        event_days.setdefault((uid, tool), set()).add(day)

    return {
        "people": people, "org_ids": org_ci, "descendants": descendants,
        "seats": seats, "prices": prices,
        "event_days": {k: sorted(v) for k, v in event_days.items()},
        "n_events": n_events, "report": rep,
    }
