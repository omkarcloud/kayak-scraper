"""Configuration for the Kayak Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT         port the API listens on (default 8000)
    KAYAK_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                 (default: none — direct). KAYAK answered every endpoint from
                 home, office and cloud server IPs in testing, so you very
                 likely don't need this. Set it only if you start seeing
                 failures at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# One KAYAK session (its cookies + form token, earned from the home page once)
# serves this many calls, or lives this many seconds, before a fresh one starts.
KAYAK_SESSION_USES = 40
KAYAK_SESSION_MAX_AGE = 1800
# After a block, new sessions keep using the block route (KAYAK_PROXY, or a
# plain fresh connection) for this many seconds.
KAYAK_BLOCK_HOLD_S = 600

KAYAK_PROXY = os.environ.get("KAYAK_PROXY") or None


def kayak_proxy():
    """The proxy for one session (None = direct)."""
    return os.environ.get("KAYAK_PROXY") or None


def kayak_block_proxy():
    """The proxy a new session uses right after a block (None = direct)."""
    return os.environ.get("KAYAK_PROXY") or None
