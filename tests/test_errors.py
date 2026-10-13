import pytest
from helpers import make_dir, client


@pytest.fixture()
def c(monkeypatch):
    d = make_dir("P1,One,ORG03,Dev,Pune\n", seats="P1,A,standard,2026-01-01,\n", prices="A,standard,19\n")
    with client(monkeypatch, d) as cl:
        yield cl


@pytest.mark.parametrize("ep", ["summary", "tools"])
@pytest.mark.parametrize("qs,code", [
    ("from=2026-07-01&to=2026-07-31&org=NOPE", 404),
    ("from=2026-07-31&to=2026-07-01", 422),
    ("from=2026-13-01&to=2026-07-31", 422), ("from=2026-02-30&to=2026-03-01", 422),
    ("from=20260701&to=2026-07-31", 422), ("from=2026-7-1&to=2026-07-31", 422),
    ("from=abc&to=def", 422), ("from=&to=2026-07-31", 422), ("to=2026-07-31", 422), ("from=2026-07-01", 422),
    ("from=2026-07-31&to=2026-07-01&org=NOPE", 422),
    ("from=0001-01-01&to=9999-12-31", 200),   # extreme but valid: must not crash
    ("from=2026-07-01&to=2026-07-01", 200),   # single day
    ("from=2026-07-01&to=2026-07-31&org=org03", 200),  # org id is case-insensitive
    ("from=2026-07-01&to=2026-07-31&org=", 200),       # blank org == no org
])
def test_status_codes(c, ep, qs, code):
    assert c.get(f"/api/{ep}?{qs}").status_code == code


def test_health_and_page(c):
    assert c.get("/health").json() == {"status": "ok"}
    assert "<form" in c.get("/").text
