"""What docker-compose.yml publishes, and where. Variables are expanded with their defaults, as compose does."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VARIABLE = re.compile(r"\$\{([A-Z_]+)(?::-([^}]*))?\}")


def rendered(env: dict[str, str] | None = None) -> dict:
    """The compose file with ${NAME:-default} replaced by the value in `env`, or by the default."""
    env = {} if env is None else env
    text = VARIABLE.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), (ROOT / "docker-compose.yml").read_text())
    return yaml.safe_load(text)["services"]


def published(services: dict):
    for name, service in services.items():
        for entry in service.get("ports") or []:
            yield name, str(entry)


def test_the_api_is_published_on_loopback_port_8110_by_default():
    assert rendered()["api"]["ports"] == ["127.0.0.1:8110:8000"]


def test_the_api_port_can_be_chosen():
    assert rendered({"API_PORT": "9011"})["api"]["ports"] == ["127.0.0.1:9011:8000"]


def test_the_web_ui_is_bound_to_loopback_by_default():
    assert rendered()["web"]["ports"] == ["127.0.0.1:3100:80"]


def test_every_published_port_is_bound_to_loopback_unless_web_bind_is_set():
    for name, entry in published(rendered()):
        assert entry.startswith("127.0.0.1:"), (name, entry)
    services = rendered({"WEB_BIND": "0.0.0.0"})
    for name, entry in published(services):
        if name != "web":
            assert entry.startswith("127.0.0.1:"), (name, entry)
    assert rendered({"WEB_BIND": "0.0.0.0"})["web"]["ports"] == ["0.0.0.0:3100:80"]


def test_only_the_web_port_reads_web_bind():
    raw = (ROOT / "docker-compose.yml").read_text()
    assert raw.count("${WEB_BIND") == 1 and '"${WEB_BIND:-127.0.0.1}:3100:80"' in raw


def test_the_port_variables_are_documented_in_env_example():
    documented = {
        line.split("=", 1)[0].strip()
        for line in (ROOT / ".env.example").read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert {"API_PORT", "WEB_BIND"} <= documented
    assert "plain HTTP" in (ROOT / ".env.example").read_text()
