"""Experience Bank: an MCP server giving Claude a persistent experience bank and application tracker.

Each user connects with a personal secret key in the URL: https://HOST/u/<key>/mcp
Their data is stored under a hash of that key, so users never see each other's data.
"""
import contextvars
import hashlib
import os
import re
from datetime import date, datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import text
from starlette.responses import JSONResponse

import db
import matching

STAGES = ["Interested", "Applied", "Online test", "Assessment centre", "Interview", "Offer", "Accepted", "Rejected", "Withdrawn"]
CLOSED = {"Offer", "Accepted", "Rejected", "Withdrawn"}
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{12,128}$")

_user: contextvars.ContextVar[str | None] = contextvars.ContextVar("user", default=None)

mcp = FastMCP(
    "Experience Bank",
    instructions=(
        "A persistent experience bank and application tracker for students. Use save_experience whenever the user "
        "describes a module, society role, project or job worth remembering; match_to_job when they paste a job "
        "description and want to apply (then draft ONLY from the returned experiences); track_application to log or "
        "review applications and deadlines."
    ),
    stateless_http=True,
    json_response=True,
    # Public hosting: the host header is the real domain, not localhost.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _uid() -> str:
    key = _user.get()
    if not key:
        raise ValueError("Missing personal key. The connector URL must look like https://HOST/u/<your-key>/mcp")
    return hashlib.sha256(key.encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_date(s: str) -> date:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Could not read the deadline '{s}'. Use YYYY-MM-DD, e.g. 2026-11-15.")


def _clean_stage(s: str) -> str:
    for known in STAGES:
        if s.strip().lower() == known.lower():
            return known
    return s.strip().title()


@mcp.tool()
def save_experience(title: str, what_i_did: str, skills: list[str], outcome: str) -> dict:
    """Save one experience (a module, society role, project or job) to the user's experience bank.

    Args:
        title: Short name, e.g. "Treasurer, Finance Society" or "Machine Learning module project".
        what_i_did: What the user personally did, in a few sentences. Be specific.
        skills: Skills demonstrated, e.g. ["budgeting", "Python", "stakeholder management"].
        outcome: The result, ideally with numbers, e.g. "Grew membership 40% and ran a £5k budget".
    """
    title, what_i_did, outcome = title.strip(), what_i_did.strip(), outcome.strip()
    skills = [s.strip() for s in skills if s and s.strip()]
    if not (title and what_i_did and outcome and skills):
        raise ValueError("title, what_i_did, skills and outcome are all required.")
    with db.engine.begin() as c:
        c.execute(
            text("INSERT INTO experiences (user_id,title,what_i_did,skills,outcome,created_at) "
                 "VALUES (:u,:t,:w,:s,:o,:c)"),
            dict(u=_uid(), t=title, w=what_i_did, s=", ".join(skills), o=outcome, c=_now()),
        )
        total = c.execute(text("SELECT COUNT(*) FROM experiences WHERE user_id=:u"), dict(u=_uid())).scalar()
    return {"saved": title, "total_experiences_in_bank": total}


@mcp.tool()
def match_to_job(job_description: str, max_results: int = 5) -> dict:
    """Find the user's most relevant saved experiences for a pasted job description.

    Returns real saved material, most relevant first, with the keywords that matched. Draft the
    application using ONLY these experiences; do not invent others.

    Args:
        job_description: The full job or internship description text.
        max_results: How many experiences to return (1-10).
    """
    max_results = max(1, min(int(max_results), 10))
    with db.engine.connect() as c:
        rows = c.execute(
            text("SELECT id,title,what_i_did,skills,outcome FROM experiences WHERE user_id=:u"), dict(u=_uid())
        ).mappings().all()
    exps = [dict(r) for r in rows]
    if not exps:
        return {"matches": [], "note": "The experience bank is empty. Ask the user to describe experiences, then call save_experience."}
    matches = matching.rank(job_description, exps, max_results)
    if not matches:
        return {"matches": [], "bank_size": len(exps),
                "note": "No saved experience overlaps with this description. Suggest the user add more experiences."}
    return {"matches": matches, "bank_size": len(exps)}


@mcp.tool()
def track_application(company: str = "", role: str = "", deadline: str = "", stage: str = "") -> dict:
    """Save or update a job application, and list all applications including those due in the next 7 days.

    To save: give company and role, plus optionally deadline (YYYY-MM-DD) and stage. Calling again with the
    same company and role updates it. To just list, call with no arguments.

    Args:
        company: Company name.
        role: Role or internship title.
        deadline: Application deadline, YYYY-MM-DD (DD/MM/YYYY also accepted).
        stage: One of Interested, Applied, Online test, Assessment centre, Interview, Offer, Accepted, Rejected, Withdrawn.
    """
    uid, saved = _uid(), None
    company, role = company.strip(), role.strip()
    if bool(company) != bool(role):
        raise ValueError("To save an application, give both company and role.")
    with db.engine.begin() as c:
        if company:
            dl = _parse_date(deadline).isoformat() if deadline.strip() else None
            existing = c.execute(
                text("SELECT id,deadline,stage FROM applications WHERE user_id=:u AND lower(company)=lower(:c) "
                     "AND lower(role)=lower(:r)"), dict(u=uid, c=company, r=role)).mappings().first()
            if existing:
                c.execute(text("UPDATE applications SET deadline=:d, stage=:s, updated_at=:t WHERE id=:i"),
                          dict(d=dl or existing["deadline"], s=_clean_stage(stage) if stage.strip() else existing["stage"],
                               t=_now(), i=existing["id"]))
                saved = "updated"
            else:
                c.execute(text("INSERT INTO applications (user_id,company,role,deadline,stage,updated_at) "
                               "VALUES (:u,:c,:r,:d,:s,:t)"),
                          dict(u=uid, c=company, r=role, d=dl, s=_clean_stage(stage) if stage.strip() else "Interested", t=_now()))
                saved = "created"
        rows = c.execute(text("SELECT company,role,deadline,stage FROM applications WHERE user_id=:u"),
                         dict(u=uid)).mappings().all()
    today = date.today()
    apps = [dict(r) for r in rows]
    apps.sort(key=lambda a: (a["deadline"] is None, a["deadline"] or ""))
    for a in apps:
        if a["deadline"]:
            a["days_left"] = (date.fromisoformat(a["deadline"]) - today).days
    due = [a for a in apps if a["deadline"] and a["stage"] not in CLOSED
           and 0 <= a["days_left"] <= 7]
    overdue = [a for a in apps if a["deadline"] and a["stage"] not in CLOSED
               and a["days_left"] < 0 and a["stage"] in ("Interested",)]
    return {"result": saved or "listed", "today": today.isoformat(), "due_in_next_7_days": due,
            "overdue_not_yet_applied": overdue, "all_applications": apps}


# --- web app: wraps the MCP app so /u/<key>/mcp works, plus a health check -------------------------

def build_app():
    inner = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            if path in ("/", "/healthz"):
                await JSONResponse({"status": "ok", "service": "experience-bank"})(scope, receive, send)
                return
            m = re.match(r"^/u/([^/]+)/mcp/?$", path)
            if not m or not KEY_RE.match(m.group(1)):
                await JSONResponse(
                    {"error": "Use /u/<your-key>/mcp where the key is 12-128 letters, digits, - or _."},
                    status_code=404)(scope, receive, send)
                return
            token = _user.set(m.group(1))
            scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
            try:
                await inner(scope, receive, send)
            finally:
                _user.reset(token)
            return
        await inner(scope, receive, send)  # lifespan etc.

    return app


db.init()
app = build_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
