import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

HEAD = {
    "people": "user_id,name,org_unit_id,role,location\n",
    "org_units": "org_unit_id,name,parent_id,level\n",
    "seats": "user_id,tool,tier,granted_on,revoked_on\n",
    "price_list": "tool,tier,monthly_price_usd\n",
    "activity_events": "user_id,tool,event_type,event_ts\n",
}
ORGS = "ORG01,Eng,,L3\nORG02,Plat,ORG01,L4\nORG03,Team,ORG02,L6\n"


def make_dir(people="", orgs=ORGS, seats="", prices="", events=""):
    d = Path(tempfile.mkdtemp())
    for name, body in dict(people=people, org_units=orgs, seats=seats, price_list=prices, activity_events=events).items():
        (d / f"{name}.csv").write_text(HEAD[name] + body, newline="")
    return d


def client(monkeypatch, data_dir):
    import app.main as m
    monkeypatch.setattr(m, "DATA_DIR", data_dir)
    return TestClient(m.app)
