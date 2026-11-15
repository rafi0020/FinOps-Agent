"""Read load on the API: many signed-in people browsing dashboards and opening results.

    cd backend && uv run locust -f load/locustfile.py --host http://localhost:3100 --headless \
        -u 1000 -r 100 -t 2m --csv load/results/read-1000

Each simulated user signs in once (demo accounts), then requests pages with one to three seconds of think
time. Start the stack with docker-compose.load.yml so sign-in limits do not throttle the test itself.
"""

import random

from locust import FastHttpUser, between, task

ACCOUNTS = [
    ("viewer@northwind.demo", "Viewer#Demo2026"),
    ("analyst@northwind.demo", "Analyst#Demo2026"),
    ("admin@northwind.demo", "Admin#Demo2026"),
    ("viewer@harbor.demo", "Viewer#Demo2026"),
    ("analyst@harbor.demo", "Analyst#Demo2026"),
]
PERIODS = ["2026-Q3", "2026-Q2", "2026-Q1", "2025-Q4", "2026", "2025"]


class Reader(FastHttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        email, password = random.choice(ACCOUNTS)
        self.role = email.split("@")[0]
        response = self.client.post(
            "/api/auth/login", json={"email": email, "password": password}, name="POST /api/auth/login"
        )
        response.raise_for_status()
        self.runs: list[str] = []
        if self.role != "viewer":
            listed = self.client.get("/api/runs?limit=20", name="GET /api/runs")
            if listed.status_code == 200:
                self.runs = [r["id"] for r in listed.json()["runs"] if r["status"] == "completed"]

    @task(6)
    def overview(self) -> None:
        self.client.get(f"/api/overview?period={random.choice(PERIODS)}", name="GET /api/overview")

    @task(3)
    def me(self) -> None:
        self.client.get("/api/auth/me", name="GET /api/auth/me")

    @task(3)
    def investigations(self) -> None:
        self.client.get("/api/investigations", name="GET /api/investigations")

    @task(2)
    def alerts(self) -> None:
        self.client.get("/api/alerts/events?open_only=true", name="GET /api/alerts/events")

    @task(1)
    def catalog(self) -> None:
        self.client.get("/api/catalog", name="GET /api/catalog")

    @task(4)
    def open_run(self) -> None:
        if self.runs:
            self.client.get(f"/api/runs/{random.choice(self.runs)}", name="GET /api/runs/{id}")
