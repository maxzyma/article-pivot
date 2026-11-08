"""HTTP fetching with a retry policy for transient network drops.

Proxied TLS connections can drop mid-handshake for minutes at a time
(UNEXPECTED_EOF_WHILE_READING, connection resets, timeouts). Those are retried
on a backoff long enough to ride out such an outage; any answer from the server
other than 429/5xx (e.g. 404) is raised at once.

The orchestration layer that runs these adapters applies the same policy to its
own remote calls; keep the two in sync.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.request

# Seconds between attempts; ~5 minutes in total before giving up.
BACKOFF = (10, 30, 90, 180)
TRANSIENT = re.compile(
    r"SSL_ERROR|SSL_connect|UNEXPECTED_EOF|EOF occurred in violation"
    r"|Could not resolve|Temporary failure in name resolution|Failed to connect"
    r"|Connection (reset|refused|timed out|aborted)|Operation timed out|timed out"
    r"|Recv failure|early EOF|RPC failed|remote end hung up|unexpected disconnect"
    r"|HTTP Error (429|50[0-4])",
    re.IGNORECASE,
)


def is_transient(error: Exception) -> bool:
    return bool(TRANSIENT.search(str(error)))


def fetch_text(url: str, *, accept: str = "text/html", user_agent: str = "article-pivot/0.1",
               timeout: float = 45) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": accept})
    for delay in (*BACKOFF, None):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8",
                                              errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if delay is None or not is_transient(error):
                raise
        time.sleep(delay)
    raise AssertionError("unreachable")
