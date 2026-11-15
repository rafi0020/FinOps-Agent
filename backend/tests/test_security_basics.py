from app.security.crypto import decrypt, encrypt
from app.security.passwords import hash_password, verify_password
from app.security.redact import redact


async def test_security_headers_on_every_response(client):
    h = (await client.get("/api/auth/me")).headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in h["Content-Security-Policy"]
    assert h["Cache-Control"] == "no-store"


def test_password_hash_verifies_and_is_salted():
    a, b = hash_password("Correct-Horse-9"), hash_password("Correct-Horse-9")
    assert a != b and a.startswith("scrypt$")
    assert verify_password("Correct-Horse-9", a) and not verify_password("correct-horse-9", a)
    assert not verify_password("anything", "not-a-hash")


def test_redact_masks_sensitive_keys_and_secret_looking_values():
    out = redact(
        {
            "model": "gpt",
            "config": {"api_key": "abc", "Authorization": "Bearer x", "timeout": 5},
            "note": "the key is sk-test0000000000000abcdefgh and more",
            "items": [{"password": "p"}, "plain"],
            "empty_token": "",
        }
    )
    assert out["config"] == {"api_key": "[redacted]", "Authorization": "[redacted]", "timeout": 5}
    assert out["note"] == "the key is [redacted] and more"
    assert out["items"] == [{"password": "[redacted]"}, "plain"]
    assert out["model"] == "gpt" and out["empty_token"] == ""


def test_encrypt_round_trips_and_is_not_plaintext():
    token = encrypt("sk-live-value")
    assert "sk-live-value" not in token and decrypt(token) == "sk-live-value"


def test_counts_named_like_secrets_are_not_masked():
    """Found by the AgentOps evaluation: input_tokens and output_tokens came back as [redacted]."""
    out = redact({"input_tokens": 120, "max_tokens": 4096, "tokens": 9, "api_key": "x", "access_token": "y", "Authorization": "z",
                  "client_secret": "s", "password": "p", "monkey": "banana", "cookie": "c", "key": "k"})  # fmt: skip
    assert out == {"input_tokens": 120, "max_tokens": 4096, "tokens": 9, "api_key": "[redacted]", "access_token": "[redacted]",
                   "Authorization": "[redacted]", "client_secret": "[redacted]", "password": "[redacted]", "monkey": "banana",
                   "cookie": "[redacted]", "key": "[redacted]"}  # fmt: skip
