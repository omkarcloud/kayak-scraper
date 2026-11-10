"""Offline tests for the KAYAK session mint and the pooled sessions
(kayak/fetch.py). No network: a fake curl session stands in for curl_cffi
inside a real fetch._Session, and the pool's mint is faked.

    python -m pytest kayak/test_fetch.py -q
"""
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kayak import fetch  # noqa: E402

HOME_HTML = '<html><title>KAYAK</title><script>{"formtoken":"tok123"}</script></html>'


class FakeResponse:
    def __init__(self, status=200, text="", url="https://www.kayak.com/?ispredir=true"):
        self.status_code = status
        self.text = text
        self.url = url

    def json(self):
        import json
        return json.loads(self.text)


class FakeSession:
    """The curl stand-in: scripted responses, every URL recorded."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("headers") or {}))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def ident(responses):
    """A real pooled session whose curl handle is a FakeSession."""
    sess = fetch._Session(None)
    sess.curl.close()
    sess.curl = FakeSession(responses)
    return sess


@pytest.fixture
def pool(monkeypatch):
    """kayak's pool with a counting fake mint: `pool.script(*per_session)`
    queues the responses each minted session answers."""
    monkeypatch.setattr(fetch.config, "MAX_RETRIES", 1)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_hold_until", 0.0)
    queue, minted = [], []

    def fake_mint(key, hint=None):
        sess = ident(queue.pop(0) if queue else [])
        minted.append(sess)
        return sess

    p = fetch._sessions
    p.clear()
    p._mint_fn = fake_mint
    p.minted = minted
    p.script = lambda *per_session: queue.extend(list(r) for r in per_session)
    yield p
    p.clear()
    p._mint_fn = fetch._mint


def test_mint_reads_the_inline_token_from_the_geo_safe_home_page():
    sess = ident([FakeResponse(text=HOME_HTML)])
    assert fetch._mint_session(sess) == "tok123" and sess.kayak_token == "tok123"
    assert sess.curl.calls[0][0] == "https://www.kayak.com/?ispredir=true"


def test_mint_on_a_country_site_is_blocked():
    sess = ident([FakeResponse(text=HOME_HTML, url="https://www.kayak.co.in/?ispredir=true")])
    with pytest.raises(fetch.KayakBlocked, match="kayak.co.in"):
        fetch._mint_session(sess)


@pytest.mark.parametrize("response", [
    FakeResponse(status=403, text="denied"),
    FakeResponse(text='<html><title>Security check</title></html>'),
    FakeResponse(text="<html><title>KAYAK</title>no token here</html>"),
])
def test_mint_without_a_usable_page_is_blocked(response):
    with pytest.raises(fetch.KayakBlocked):
        fetch._mint_session(ident([response]))


def test_api_get_keeps_a_blocked_mint_blocked(pool):
    """A captcha on the mint page must surface as KayakBlocked (block hold +
    fresh exit), not be re-wrapped as a plain transport failure; the
    session that met it is retired."""
    pool.script([FakeResponse(status=429, text="slow down")])
    with pytest.raises(fetch.KayakBlocked):
        fetch.fetch_static_details("61867")
    assert fetch._hold_until > 0      # the block started the datacenter hold
    assert pool.minted[0].closed and pool.stats()["idle"] == 0


def test_api_get_sends_the_token_and_referer(pool):
    pool.script([FakeResponse(text=HOME_HTML), FakeResponse(text='{"overview": {"hotelId": 61867}}')])
    data = fetch.fetch_static_details("61867")
    assert data == {"overview": {"hotelId": 61867}}
    sess = pool.minted[0].curl
    url, headers = sess.calls[1]
    assert url.startswith("https://www.kayak.com/i/api/search/v1/static/hotels/details?hid=61867")
    assert headers["x-csrf"] == "tok123"
    assert headers["referer"] == "https://www.kayak.com/Hotel.61867.ksp"
    assert headers["x-requested-with"] == "XMLHttpRequest"


def test_three_threads_share_one_minted_session_and_a_block_retires_it(pool):
    """Three sequential calls on three different threads ride ONE session:
    the home page is minted once (before: once per thread). A 429 then
    retires it (closed, nothing idle)."""
    pool.script([FakeResponse(text=HOME_HTML)] + [FakeResponse(text='{"overview": {"hotelId": %d}}' % i) for i in (1, 2, 3)]
                + [FakeResponse(status=429, text="slow down")])
    results = []
    for _ in range(3):
        t = threading.Thread(target=lambda: results.append(fetch.fetch_static_details("61867")))
        t.start()
        t.join()
    assert [r["overview"]["hotelId"] for r in results] == [1, 2, 3]
    assert len(pool.minted) == 1
    sess = pool.minted[0]
    assert sum(1 for url, _ in sess.curl.calls if url.endswith("?ispredir=true")) == 1    # one warm-up
    assert pool.stats()["idle"] == 1 and not sess.closed
    with pytest.raises(fetch.KayakBlocked):
        fetch.fetch_static_details("61867")
    assert sess.dead and sess.closed and pool.stats()["idle"] == 0
