"""End-to-end checks: spins up the real app and calls tools over the MCP protocol."""
import os, tempfile, asyncio, json
from datetime import date, timedelta

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")

import httpx
import pytest
import server  # noqa: E402

KEY_A, KEY_B = "alice-secret-key-123", "bob-secret-key-45678"


def call(client, key, tool, args, id_=1):
    r = client.post(f"/u/{key}/mcp", json={"jsonrpc": "2.0", "id": id_, "method": "tools/call",
                    "params": {"name": tool, "arguments": args}},
                    headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert not res.get("isError"), res
    return res["structuredContent"] if "structuredContent" in res else json.loads(res["content"][0]["text"])


@pytest.fixture(scope="module")
def client():
    from starlette.testclient import TestClient
    with TestClient(server.app, base_url="https://example.onrender.com") as c:
        yield c


def test_health(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_bad_key_rejected(client):
    assert client.post("/u/short/mcp", json={}).status_code == 404
    assert client.post("/mcp", json={}).status_code == 404


def test_lists_three_tools(client):
    r = client.post(f"/u/{KEY_A}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Accept": "application/json, text/event-stream"})
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == {"save_experience", "match_to_job", "track_application"}


def test_save_and_match(client):
    call(client, KEY_A, "save_experience", dict(
        title="Treasurer, Finance Society", what_i_did="Managed a £5k budget, ran sponsorship pitches to banks.",
        skills=["budgeting", "negotiation", "Excel"], outcome="Raised £2k in sponsorship"))
    out = call(client, KEY_A, "save_experience", dict(
        title="Football club captain", what_i_did="Organised weekly training and fixtures.",
        skills=["leadership", "teamwork"], outcome="Won league"))
    assert out["total_experiences_in_bank"] == 2
    m = call(client, KEY_A, "match_to_job", dict(job_description=
        "Finance intern: support budgeting and forecasting in Excel, liaise with sponsors and negotiate with suppliers."))
    assert m["matches"][0]["title"] == "Treasurer, Finance Society"
    assert "budget" in " ".join(m["matches"][0]["matched_terms"])


def test_users_are_isolated(client):
    m = call(client, KEY_B, "match_to_job", dict(job_description="budgeting in Excel"))
    assert m["matches"] == [] and "empty" in m["note"]


def test_tracker(client):
    soon = (date.today() + timedelta(days=3)).isoformat()
    later = (date.today() + timedelta(days=30)).isoformat()
    call(client, KEY_A, "track_application", dict(company="Barclays", role="Finance Intern", deadline=soon, stage="interested"))
    r = call(client, KEY_A, "track_application", dict(company="Deloitte", role="Analyst", deadline=later, stage="Applied"))
    assert r["result"] == "created" and len(r["all_applications"]) == 2
    assert [a["company"] for a in r["due_in_next_7_days"]] == ["Barclays"]
    r = call(client, KEY_A, "track_application", dict(company="barclays", role="finance intern", stage="Applied"))
    assert r["result"] == "updated" and len(r["all_applications"]) == 2
    r = call(client, KEY_A, "track_application", {})
    assert r["result"] == "listed" and r["all_applications"][0]["company"] == "Barclays"
