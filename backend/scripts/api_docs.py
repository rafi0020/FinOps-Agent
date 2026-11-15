"""Writes docs/API.md from the application's OpenAPI schema:  python -m scripts.api_docs"""

from pathlib import Path

from app.main import create_app

INTRO = """# API reference

Generated from the application's OpenAPI schema (`python -m scripts.api_docs`). The interactive version, with
request and response schemas, is served at `/docs` on the API (http://localhost:8110/docs).

All routes under `/api` except sign-up and sign-in need the session cookie. State-changing requests also need
the `X-CSRF-Token` header, whose value is returned by sign-in and by `GET /api/auth/me`. Errors are
`{"detail": "..."}` with a conventional status: 401 not signed in, 403 role or CSRF, 404 not found (also
returned for another organisation's objects), 409 conflicting state, 422 invalid input, 429 limit reached
(with `Retry-After`).
"""
EVENTS = """## Live events

`GET /api/runs/{run_id}/events` is a Server-Sent Events stream. Each event has an `id`; send it back as
`Last-Event-ID` to resume. Event types: `run.status`, `step.started`, `step.finished`, `approval.requested`,
`question.asked`, `report.ready`. The stream closes after a `run.status` event with a final status.
"""
ORDER = ["auth", "users", "runs", "approvals", "investigations", "alerts", "overview", "catalog", "usage",
         "settings", "audit", "evaluation", "health"]  # fmt: skip


def main() -> None:
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for path, methods in create_app().openapi()["paths"].items():
        for method, op in methods.items():
            text = (op.get("description") or op.get("summary") or "").strip().split("\n")[0]
            groups.setdefault((op.get("tags") or ["other"])[0], []).append((method.upper(), path, text))
    out = [INTRO]
    for tag in ORDER:
        rows = sorted(groups.get(tag, []), key=lambda r: (r[1], r[0]))
        if rows:
            out += [f"## {tag.capitalize()}\n", "| Method | Path | What it does |", "|---|---|---|"]
            out += [f"| {m} | `{p}` | {t} |" for m, p, t in rows] + [""]
    out.append(EVENTS)
    Path(__file__).resolve().parents[2].joinpath("docs", "API.md").write_text("\n".join(out))


if __name__ == "__main__":
    main()
