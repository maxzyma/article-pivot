"""HTTP fetching with a short retry for transient network drops.

Proxied connections drop now and then (UNEXPECTED_EOF_WHILE_READING, resets,
timeouts); a fresh connection usually works within seconds. Only such transport
failures are retried, briefly; anything naming authentication, permissions or a
certificate, and any server answer other than 429/502/503/504, is raised at once.
A host that stays unreachable is left to the caller's next scheduled run.

The orchestration layer that runs these adapters applies the same policy to its
own remote calls; keep the two in sync.
"""
from __future__ import annotations

import random
import re
import sys
import time
import urllib.error
import urllib.request

NETWORK_ATTEMPTS = 3
BACKOFF_SECONDS = (5, 15)
TRANSIENT = re.compile(
    r"time limit|timed? out|connection (reset|closed)|unexpected disconnect|remote end hung up"
    r"|early eof|ssl_error_syscall|ssl.*(interrupt|reset|closed)|recv failure|send failure"
    r"|unexpected_eof|eof occurred in violation of protocol"
    r"|empty reply from server|returned error: (502|503|504)|http/\S+ (502|503|504)"
    r"|http error (429|502|503|504)"
)
FINAL = re.compile(
    r"authentication|permission|denied|repository not found|could not read username"
    r"|terminal prompts disabled|certificate|returned error: (401|403|404)|could not resolve host"
)


def transient_failure(text: str) -> bool:
    lowered = text.lower()
    return bool(TRANSIENT.search(lowered)) and not FINAL.search(lowered)


def backoff(attempt: int) -> float:
    """Delay before retry number ``attempt`` (1-based), with jitter."""
    return BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1] + random.uniform(0, 3)


def fetch_text(url: str, *, accept: str = "text/html", user_agent: str = "article-pivot/0.1",
               timeout: float = 45) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": accept})
    for attempt in range(1, NETWORK_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8",
                                              errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == NETWORK_ATTEMPTS or not transient_failure(str(error)):
                raise
            delay = backoff(attempt)
            print(f"transient network failure (attempt {attempt}/{NETWORK_ATTEMPTS}), "
                  f"retrying {url} in {delay:.0f}s: {error}", file=sys.stderr, flush=True)
        time.sleep(delay)
    raise AssertionError("unreachable")
