"""Stdlib smoke checks for the canonical server.redact contract."""
import ipaddress
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.redact import scrub_text, scrub_url_query


def check(value, expected):
    actual = scrub_text(value)
    assert actual == expected, (value, actual, expected)
    assert scrub_text(actual) == actual, ("not idempotent", value, actual)


for address in ("::1", "2001:db8::24", "2001:0db8:0000:0000:0000:0000:0000:0024"):
    assert ipaddress.IPv6Address(address)
    check(address, "[ip]")
check("https://[2001:db8::24]:27124 (bridge-only, self-signed)", "https://[ip]:27124 (bridge-only, self-signed)")
check("mission.onendo.cloud Keystone status=running t_43f53b7b 2026-11-09T05:14:00Z", "mission.onendo.cloud Keystone status=running t_43f53b7b 2026-11-09T05:14:00Z")
check("Authorization: Bearer sentinel", "Authorization: [redacted]")
check("Cookie: session=sentinel", "Cookie: [redacted]")
check("https://host/path?sig=sentinel&status=running", "https://host/path?sig=[redacted]&status=running")
check("-----BEGIN RSA PRIVATE KEY-----\nSENTINEL-PRIVATE\n-----END RSA PRIVATE KEY-----", "[redacted-private-key]")
check("-----BEGIN OPENSSH PRIVATE KEY-----", "[redacted-private-key]")
url = scrub_url_query("https://host/?sig=sentinel&status=running")
assert "sentinel" not in url and "status=running" in url
assert scrub_url_query(url) == url
print("redact smoke: PASS")
