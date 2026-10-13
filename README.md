# AI tool adoption and spend API (Helix Labs)
python -m pip install -r requirements.txt && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000




Then open http://localhost:8000/ (test page) or call:

```
curl "http://localhost:8000/health"
curl "http://localhost:8000/api/summary?from=2026-07-01&to=2026-07-31&org=ORG05"
curl "http://localhost:8000/api/tools?from=2026-07-01&to=2026-07-31"
```

## Tests (offline)
```
pip install -r requirements.txt
python -m pytest -q
```
Covers the Appendix P worked example, window edges, error codes, dirty-data start-up, and a randomised comparison against a naive day-by-day implementation.

