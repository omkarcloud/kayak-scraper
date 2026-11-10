"""The language every request announces (the Accept-Language header).

The hosted API matches it to the country of the IP each request leaves
through; this open-source copy sends one US English list everywhere, the
language www.kayak.com serves its pages in.
"""

ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def accept_language(proxy=None, country=None):
    """The Accept-Language for a session (any exit)."""
    return ACCEPT_LANGUAGE


def site_accept_language(site):
    """The Accept-Language for a module's fixed request headers."""
    return ACCEPT_LANGUAGE
