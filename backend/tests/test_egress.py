"""Outbound model calls: which destinations are refused, and that the connection goes to the address that was checked."""

import socket

import httpcore
import pytest
from httpcore._backends.auto import AutoBackend

from app.config import get_settings
from app.llm.base import LLMError
from app.llm.factory import validate_base_url
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.types import Message


@pytest.fixture
def private_allowed(monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_private_llm_urls", True)


@pytest.fixture
def private_refused(monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_private_llm_urls", False)


def fake_dns(monkeypatch, *answers: str) -> list[str]:
    """Each lookup returns the next answer (the last one repeats). Returns the list of hosts looked up."""
    looked_up: list[str] = []

    def getaddrinfo(host, port, *args, **kwargs):
        looked_up.append(host)
        ip = answers[min(len(looked_up), len(answers)) - 1]
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return looked_up


@pytest.fixture
def dialled(monkeypatch) -> list[tuple[str, int]]:
    """Records every TCP connection the HTTP stack attempts, and refuses it so nothing leaves the test."""
    attempts: list[tuple[str, int]] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        attempts.append((host, port))
        raise httpcore.ConnectError("refused by the test")

    monkeypatch.setattr(AutoBackend, "connect_tcp", connect_tcp)
    return attempts


# --- which addresses are refused -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://100.64.0.1/v1",  # carrier-grade NAT
        "http://100.127.255.254/v1",
        "http://100.100.100.200/v1",  # cloud metadata on some providers, inside CGNAT
        "http://240.0.0.1/v1",  # reserved
        "http://198.18.0.1/v1",  # benchmarking
        "http://224.0.0.1/v1",  # multicast
        "http://0.0.0.0/v1",  # unspecified
        "http://169.254.169.254/v1",  # link-local metadata
        "http://[fe80::1]/v1",
        "http://[::ffff:169.254.169.254]/v1",  # IPv4-mapped form of the metadata address
    ],
)
def test_reserved_and_metadata_addresses_are_refused_even_when_private_urls_are_allowed(url, private_allowed):
    with pytest.raises(ValueError):
        validate_base_url(url)


@pytest.mark.parametrize(
    "url", ["http://10.1.1.1/v1", "http://127.0.0.1:20128/v1", "http://192.168.1.5/v1", "http://[::1]:20128/v1"]
)
def test_private_addresses_follow_the_setting(url, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_private_llm_urls", True)
    validate_base_url(url)
    monkeypatch.setattr(get_settings(), "allow_private_llm_urls", False)
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_a_public_address_is_accepted(private_refused):
    validate_base_url("https://8.8.8.8/v1")


def test_a_hostname_is_refused_when_any_of_its_addresses_is_reserved(monkeypatch, private_allowed):
    def both_answers(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0)) for ip in ("8.8.8.8", "100.64.0.9")]

    monkeypatch.setattr(socket, "getaddrinfo", both_answers)
    with pytest.raises(ValueError):
        validate_base_url("https://mixed.example/v1")


# --- what the connection is made to ----------------------------------------------------------------------------


async def test_the_connection_goes_to_the_address_that_was_checked(monkeypatch, dialled, private_allowed):
    """A second lookup that would answer with the metadata address (DNS rebinding) must not be used."""
    looked_up = fake_dns(monkeypatch, "8.8.8.8", "169.254.169.254")
    provider = OpenAICompatProvider("http://gateway.example/v1", "")
    with pytest.raises(LLMError):
        await provider.complete([Message("user", "hi")], [], model="m", max_tokens=5)
    assert dialled == [("8.8.8.8", 80)]
    assert len(looked_up) == 1


async def test_a_destination_that_resolves_to_a_blocked_address_is_never_dialled(monkeypatch, dialled, private_allowed):
    fake_dns(monkeypatch, "169.254.169.254")
    provider = OpenAICompatProvider("http://metadata.example/v1", "")
    with pytest.raises(LLMError) as info:
        await provider.complete([Message("user", "hi")], [], model="m", max_tokens=5)
    assert dialled == [] and info.value.retryable is False


async def test_private_destinations_are_refused_at_connection_when_disabled(monkeypatch, dialled, private_refused):
    fake_dns(monkeypatch, "10.0.0.5")
    provider = OpenAICompatProvider("http://internal.example/v1", "")
    with pytest.raises(LLMError):
        await provider.complete([Message("user", "hi")], [], model="m", max_tokens=5)
    assert dialled == []
