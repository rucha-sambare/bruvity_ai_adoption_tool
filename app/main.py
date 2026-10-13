from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .loader import load_data
from .metrics import calculate, users_in_scope

DATA_DIR = Path(os.environ.get("HELIX_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.data = load_data(DATA_DIR)
    for line in app.state.data["report"].summary_lines():
        print(line)
    app.state.scope_cache = {}
    yield


app = FastAPI(title="AI Tool Adoption and Spend API", lifespan=lifespan)


@app.exception_handler(Exception)
async def unexpected(_request: Request, exc: Exception):  # never leak a stack trace
    return JSONResponse(status_code=500, content={"detail": "internal error"})


class Summary(BaseModel):
    licensed_users: int
    active_users: int
    engagement_pct: float
    spend: float
    idle_spend: float


class ToolRow(BaseModel):
    tool: str
    licensed_users: int
    active_users: int
    engagement_pct: float
    spend: float | None
    idle_spend: float | None
    cost_per_active: float | None


def parse_day(value: str, name: str) -> int:
    """Strict YYYY-MM-DD only (4-digit year, 2-digit month/day, real calendar date)."""
    if len(value) != 10 or value[4] != "-" or value[7] != "-" or not (value.isascii() and (value[:4] + value[5:7] + value[8:]).isdigit()):
        raise HTTPException(422, f"'{name}' must be a valid YYYY-MM-DD date")
    try:
        return date(int(value[:4]), int(value[5:7]), int(value[8:])).toordinal()
    except ValueError:
        raise HTTPException(422, f"'{name}' must be a valid YYYY-MM-DD date") from None


def run(request: Request, frm: str, to: str, org: str | None):
    start, end = parse_day(frm, "from"), parse_day(to, "to")
    if start > end:
        raise HTTPException(422, "'from' must be on or before 'to'")
    data = request.app.state.data
    key = None
    if org is not None and org.strip():
        key = data["org_ids"].get(org.strip().upper())  # exact id, case/space tolerant
        if key is None:
            raise HTTPException(404, f"Unknown org: {org}")
    cache = request.app.state.scope_cache
    if key not in cache:
        cache[key] = users_in_scope(data, key)
    return calculate(data, start, end, cache[key])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/summary", response_model=Summary)
def summary(request: Request, from_: str = Query(alias="from"), to: str = Query(), org: str | None = None):
    return run(request, from_, to, org)[0]


@app.get("/api/tools", response_model=list[ToolRow])
def tools(request: Request, from_: str = Query(alias="from"), to: str = Query(), org: str | None = None):
    return run(request, from_, to, org)[1]


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>AI Tool Adoption and Spend</title>
<style>body{font:16px system-ui,sans-serif;max-width:960px;margin:32px auto;padding:0 16px}
label{margin-right:12px}input,button{padding:8px}table{border-collapse:collapse;margin:8px 0}
td,th{border:1px solid #ccc;padding:6px 10px;text-align:right}th:first-child,td:first-child{text-align:left}
pre{background:#f3f4f6;padding:12px;overflow:auto}.err{color:#b00020}</style></head><body>
<h1>AI Tool Adoption and Spend</h1>
<form id="f"><label>From <input name="from" value="2026-07-01" placeholder="YYYY-MM-DD"></label>
<label>To <input name="to" value="2026-07-31" placeholder="YYYY-MM-DD"></label>
<label>Org (optional) <input name="org" placeholder="ORG05"></label><button>Get metrics</button></form>
<h2>/api/summary</h2><div id="s">Submit the form.</div><h2>/api/tools</h2><div id="t"></div>
<script>
const $=id=>document.getElementById(id);
function table(rows){const k=Object.keys(rows[0]);return '<table><tr>'+k.map(x=>'<th>'+x+'</th>').join('')+'</tr>'+
rows.map(r=>'<tr>'+k.map(x=>'<td>'+(r[x]===null?'null':r[x])+'</td>').join('')+'</tr>').join('')+'</table>';}
$('f').addEventListener('submit',async e=>{e.preventDefault();const v=new FormData($('f')),p=new URLSearchParams();
p.set('from',v.get('from').trim());p.set('to',v.get('to').trim());if(v.get('org').trim())p.set('org',v.get('org').trim());
for(const [id,ep] of [['s','summary'],['t','tools']]){$(id).textContent='Loading...';
try{const r=await fetch('/api/'+ep+'?'+p);const j=await r.json();
$(id).innerHTML=r.ok?(Array.isArray(j)?table(j):table([j])):'<pre class="err">HTTP '+r.status+' '+JSON.stringify(j)+'</pre>';
}catch(x){$(id).innerHTML='<pre class="err">'+x+'</pre>';}}});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE
