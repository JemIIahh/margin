"""The environment for host-side helper processes (git, uv, entire graph) that touch untrusted repositories.

Enough to find tools, caches, proxies and certificates; never an API key. Test code gets its own, even
tighter environment from `Sandbox.scrubbed_env`.
"""
from __future__ import annotations

import os

_ALLOWED = {
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
}


def setup_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ALLOWED or k.startswith("UV_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env
