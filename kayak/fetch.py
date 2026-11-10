"""KAYAK transport: plain curl_cffi with browser-impersonated TLS, no
browser. Egress: the pod's own IP first (knob config.KAYAK_EXIT), a sticky
datacenter exit (config.kayak_block_proxy()) for KAYAK_BLOCK_HOLD_S after a block — pod probe
2026-11-07 (scrapers-patchright-depl-74fddd498d-rfmk6): every surface below
200 from the pod's own IP, 2/2 datacenter and 2/2 US residential ports.

Sessions live in a process-wide identity_pool.Pool in exclusive mode (since
2026-11-09): a request borrows one for ONE call and hands it back, so the
next request on any of the pod's 64 threads reuses its home-page-minted
cookies + form token instead of minting its own (before, each thread kept
a session and minted per thread). A retryable failure marks the session
dead (retired on give-back), so the retry rides a fresh exit; a session is
also retired after KAYAK_SESSION_USES calls or KAYAK_SESSION_MAX_AGE seconds.

Surfaces (all read-only; KAYAK's search starts — flights / hotels / cars
polls — sit behind a reCAPTCHA gate for every curl identity and are NOT used):

  * HOME      GET /?ispredir=true  — the page that mints the API session: it
    sets the `p1.med.sid`, `kmkid`, `cluster` cookies and carries the
    session's live form token in its inline React state
    (`"formtoken":"..."`), which every /i/api call sends as X-CSRF. The token
    is bound to the session's cookies (INVALID_FORM_TOKEN on another
    session); the token baked into an seo-cached hotel page is stale. Fetched
    once per pooled session. `ispredir=true` is the flag KAYAK's own geo
    redirect appends: without it a non-US exit is 302'd to its country site
    (an Indian IP -> www.kayak.co.in, 2026-11-07) and a session minted there
    is INVALID_SESSION on www.kayak.com; with it every exit stays on .com. A
    mint that still lands on another host is Blocked (fresh exit).

  * PAGE      GET /<slug>.<hid>.ksp — the hotel's SEO page (~1.1 MB, served
    from KAYAK's seo-cache, cookie-free). /<anything>.<hid>.ksp 301s to the
    canonical slug. Its `jsonData_R9DataStorage` script carries contentState
    (amenities, photos, map POIs, nearby hotels, FAQs/tips, review summary,
    score distributions, price charts) and HotelDetailsData.rates (room rows
    x provider offers for the site's default stay). Small properties have
    NO page (real HTTP 404) while the API below still knows them, so a 404
    here means "API only", not "unknown hotel".

  * API       GET /i/api/... with X-CSRF + X-Requested-With + a kayak.com
    Referer (no Referer -> 403 ANONYMOUS_ACCESS_DENIED, no session -> 401
    INVALID_SESSION, a stale token -> 401 INVALID_FORM_TOKEN; one re-mint,
    then Blocked):
      search/v1/static/hotels/details?hid=    overview, policies, photos, geo, nearby transport, amenities
      seo/reviews/v3/filtered?objectId=       reviews, 10 per call max, startIndex paging, sortType / travelerTypes / scoresRanges / searchText / tagClusterName
      seo/reviews/v1/reviewsWithScores        overall score, counts by traveller type, pros / cons, tag counts
      seo/reviewTags/v1/hotel/tags?hotelId=   AI topic tags + AI summary
      seo/reviews/v3/hotelScoreDistributionBySource?objectId=   count / average per review source
    An unknown hid: static details is a real 404 (NOT_FOUND); the review
    routes answer 200 with empty bodies, so callers confirm through the
    details route before reporting a 404.

  * SMARTY    GET /mvm/smartyv2/search?f=j&s=&where=&lc_cc=US&lc=en&v=v2&cv=5
    — autocomplete, cookie-free, no token.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  KayakUpstreamError  transport failure / 5xx                        — retryable
  KayakBlocked        403 / 429 / captcha redirect / dead session     — retryable
  KayakBadRequest     upstream 400 (VALIDATION_ERROR)                 — never retried
  KayakNotFound       404 / NOT_FOUND                                 — never retried
"""
import os
import re
import sys
import threading
import time
from urllib.parse import urlencode, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
import identity_pool
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from kayak.refs import LOCATION_TYPES, REVIEWS_PAGE_SIZE, SITE, hotel_page_path

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 60     # the home page and a hotel page are 1.1-1.7 MB
API_TIMEOUT = 30
# The session-minting page. `ispredir=true` keeps a non-US exit on
# www.kayak.com instead of KAYAK's 302 to the exit's country site.
HOME_PATH = "/?ispredir=true"
SITE_HOST = urlparse(SITE).hostname

PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "upgrade-insecure-requests": "1",
}
API_HEADERS = {
    "accept": "*/*",
    "x-requested-with": "XMLHttpRequest",
}

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_FORMTOKEN_RE = re.compile(r'"formtoken":"([^"]+)"')
_CAPTCHA_MARKERS = ("/security/check", "BOT_CAPTCHA_REDIRECT", "captchaRedirectUrl")
_SESSION_CODES = ("INVALID_SESSION", "INVALID_FORM_TOKEN", "ANONYMOUS_ACCESS_DENIED")


class KayakUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class KayakBlocked(KayakUpstreamError, Blocked):
    """403 / 429, a captcha redirect, or a session the site will not mint — retryable."""


class KayakBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class KayakNotFound(NotFound):
    """Hotel does not exist — never retried."""


# ---- pooled sessions -----------------------------------------------------------
# A session holds the API cookies + the form token it minted from the home
# page; both die with the session. It owns ONE curl handle, so the pool lends
# it to one request at a time; threads take turns on it.
_hold_lock = threading.Lock()
_hold_until = 0.0     # new sessions ride a datacenter exit until this time (after a block)


def _proxy_for_new_session():
    """config.kayak_proxy() (None = the pod's own IP), or a datacenter exit
    while a block hold is running on the direct tier."""
    proxy = config.kayak_proxy()
    if proxy is None and time.monotonic() < _hold_until:
        return config.kayak_block_proxy()
    return proxy


def _note_block():
    global _hold_until
    with _hold_lock:
        _hold_until = max(_hold_until, time.monotonic() + config.KAYAK_BLOCK_HOLD_S)


class _Session(identity_pool.Identity):
    """One curl session on one exit plus the form token it minted
    (`kayak_token`, None until the first /i/api call mints it)."""

    def __init__(self, proxy):
        from curl_cffi import requests as curl_requests
        super().__init__(exit=proxy)
        self.curl = curl_requests.Session(impersonate=IMPERSONATE, use_thread_local_curl=False)
        self.curl.headers["accept-language"] = egress.accept_language(proxy)
        if proxy:
            self.curl.proxies = {"http": proxy, "https": proxy}
        self.kayak_token = None
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.curl.close()
        except Exception:
            pass


def _mint(key, hint=None):
    """The pool's mint: a cold session on the tier of the moment (the home
    page is loaded by the first /i/api call, see _mint_session)."""
    return _Session(_proxy_for_new_session())


_sessions = identity_pool.Pool(
    "kayak", _mint, mode="exclusive",
    budget=lambda: config.KAYAK_SESSION_USES,
    max_age=lambda: config.KAYAK_SESSION_MAX_AGE,
    on_retire=lambda ident, reason: ident.close())


def _on_session(fn):
    """fn(sess) on a borrowed session. A retryable failure marks it dead
    (retired on give-back: its exit, cookies and token go with it), so the
    retry rides a fresh exit."""
    sess = _sessions.borrow()
    try:
        return fn(sess)
    except KayakUpstreamError:
        sess.dead = True
        raise
    finally:
        _sessions.give_back(sess)


def _retrying(fn):
    """Run fn() under the shared retry policy (KayakUpstreamError only;
    NotFound / BadRequest surface immediately). A block starts the
    datacenter hold for new sessions; the failed call already retired its
    session (_on_session)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except KayakUpstreamError as e:
            last = e
            if isinstance(e, KayakBlocked):
                _note_block()
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _page_title(text):
    match = _TITLE_RE.search(text or "")
    return match.group(1).strip() if match else ""


def _looks_captcha(text):
    head = (text or "")[:6000]
    return any(m in head for m in _CAPTCHA_MARKERS) or "security check" in _page_title(head).lower()


def _mint_session(sess):
    """GET the home page on this session: cookies land in the jar, the live
    form token is read from the inline state. Blocked when the page carries
    no token (a captcha page or an interstitial) or the exit was redirected
    off www.kayak.com (a session minted on a country site is useless here)."""
    try:
        resp = sess.curl.get(SITE + HOME_PATH, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT)
    except Exception as e:
        raise KayakUpstreamError(f"home page request failed: {type(e).__name__}: {e}")
    if resp.status_code in (403, 429) or _looks_captcha(resp.text):
        raise KayakBlocked(f"HTTP {resp.status_code} on the home page (session not minted)")
    if resp.status_code != 200:
        raise KayakUpstreamError(f"HTTP {resp.status_code} on the home page")
    landed = urlparse(str(resp.url)).hostname
    if landed and landed != SITE_HOST:
        raise KayakBlocked(f"home page redirected to {landed} (session not minted)")
    match = _FORMTOKEN_RE.search(resp.text)
    if not match:
        raise KayakBlocked("home page carried no form token")
    sess.kayak_token = match.group(1)
    return sess.kayak_token


def _api_headers(sess, referer):
    token = sess.kayak_token or _mint_session(sess)
    return {**API_HEADERS, "x-csrf": token, "referer": referer}


def _error_codes(resp):
    try:
        payload = resp.json()
    except Exception:
        return []
    errors = payload.get("errors") if isinstance(payload, dict) else None
    return [str(e.get("code") or "") for e in errors or [] if isinstance(e, dict)]


def _api_get(path, params, referer, label):
    """GET an /i/api route as the page's own XHR; one session re-mint on a
    dead session / stale token (the borrowed session is retired and another
    borrowed), then Blocked."""
    url = SITE + path + ("?" + urlencode(params) if params else "")

    def once():
        sess = _sessions.borrow()
        try:
            for attempt in (1, 2):
                # minted outside the try: a Blocked mint must stay Blocked (block
                # hold + fresh exit), not turn into a plain transport failure
                headers = _api_headers(sess, referer)
                try:
                    resp = sess.curl.get(url, headers=headers, timeout=API_TIMEOUT)
                except Exception as e:
                    raise KayakUpstreamError(f"request failed: {type(e).__name__}: {e}")
                if resp.status_code in (401, 403):
                    codes = _error_codes(resp)
                    if attempt == 1 and any(c in _SESSION_CODES for c in codes):
                        sess.dead = True
                        _sessions.give_back(sess)
                        sess = None
                        sess = _sessions.borrow()
                        continue
                    raise KayakBlocked(f"HTTP {resp.status_code} for {label}: {','.join(codes) or resp.text[:120]}")
                break
            if resp.status_code == 404:
                raise KayakNotFound(f"{label} not found")
            if resp.status_code == 400:
                raise KayakBadRequest(resp.text[:200])
            if resp.status_code == 429:
                raise KayakBlocked(f"HTTP 429 for {label}")
            if resp.status_code != 200:
                raise KayakUpstreamError(f"HTTP {resp.status_code} for {label}")
            if not resp.text.strip():
                return None      # reviewsWithScores answers an empty 200 for a hotel without reviews
            try:
                return resp.json()
            except Exception:
                if _looks_captcha(resp.text):
                    raise KayakBlocked(f"captcha page for {label}")
                raise KayakUpstreamError(f"non-JSON response for {label}: {resp.text[:120]}")
        except KayakUpstreamError:
            if sess is not None:
                sess.dead = True
            raise
        finally:
            if sess is not None:
                _sessions.give_back(sess)
    return _retrying(once)


# ---- pages ---------------------------------------------------------------------------

def fetch_hotel_page(hid):
    """GET the hotel's SEO page HTML, or None when the site has no page for
    it (HTTP 404 — the static API may still know the hotel)."""
    def once(sess):
        try:
            resp = sess.curl.get(SITE + hotel_page_path(hid), headers=PAGE_HEADERS,
                                 timeout=PAGE_TIMEOUT, allow_redirects=True)
        except Exception as e:
            raise KayakUpstreamError(f"request failed: {type(e).__name__}: {e}")
        if resp.status_code == 404:
            return None
        if resp.status_code in (403, 429) or _looks_captcha(resp.text):
            raise KayakBlocked(f"HTTP {resp.status_code} for hotel page {hid}")
        if resp.status_code != 200:
            raise KayakUpstreamError(f"HTTP {resp.status_code} for hotel page {hid}")
        if "Page not found" in _page_title(resp.text):
            return None
        return resp.text
    return _retrying(lambda: _on_session(once))


# ---- API -----------------------------------------------------------------------------

def _referer(hid):
    return SITE + hotel_page_path(hid)


def fetch_static_details(hid):
    """The static hotel details JSON (overview / photos / geolocation /
    nearby transport / amenities / freebies). A real 404 for an unknown id."""
    return _api_get("/i/api/search/v1/static/hotels/details",
                    {"hid": hid, "hotelImageWidth": 968, "hotelImageHeight": 607, "reviewLimit": 0},
                    _referer(hid), f"hotel {hid}")


def fetch_reviews(hid, start_index=0, sort="recent", traveller_types=None, score_range=None,
                  search=None, topic=None):
    """One page (10) of reviews. `score_range` is (min, max) on the site's
    0-100 scale; an unknown hotel answers {"reviewCount": 0, "reviews": []}."""
    params = {"objectId": hid, "reviewType": "hotel", "amount": REVIEWS_PAGE_SIZE,
              "startIndex": start_index, "includeReviewLink": "true", "sortType": sort}
    if traveller_types:
        params["travelerTypes"] = ",".join(traveller_types)
    if score_range:
        params["scoresRanges"] = f"{score_range[0]}-{score_range[1]}"
    if search:
        params["searchText"] = search
    if topic:
        params["tagClusterName"] = topic
    return _api_get("/i/api/seo/reviews/v3/filtered", params, _referer(hid), f"reviews of hotel {hid}")


def fetch_review_scores(hid):
    """Overall score, counts by traveller type, pros / cons sentiments, tag
    counts (+ 10 reviews). None when the hotel has no reviews (empty 200)."""
    return _api_get("/i/api/seo/reviews/v1/reviewsWithScores", {"reviewType": "hotel", "objectId": hid},
                    _referer(hid), f"review scores of hotel {hid}")


def fetch_review_tags(hid):
    """AI topic tags with sentiment + the AI review summary."""
    return _api_get("/i/api/seo/reviewTags/v1/hotel/tags", {"hotelId": hid},
                    _referer(hid), f"review tags of hotel {hid}")


def fetch_score_by_source(hid):
    """Review count / average per source site (Booking.com, Agoda, ...)."""
    return _api_get("/i/api/seo/reviews/v3/hotelScoreDistributionBySource", {"objectId": hid},
                    _referer(hid), f"review sources of hotel {hid}")


# ---- autocomplete --------------------------------------------------------------------

def fetch_locations(query, kind="stays"):
    """The smarty autocomplete list (cookie-free, no token)."""
    params = {"f": "j", "where": query, "lc_cc": "US", "lc": "en", "v": "v2", "cv": "5",
              **LOCATION_TYPES[kind]}

    def once(sess):
        try:
            resp = sess.curl.get(SITE + "/mvm/smartyv2/search?" + urlencode(params),
                                 headers=API_HEADERS, timeout=API_TIMEOUT)
        except Exception as e:
            raise KayakUpstreamError(f"request failed: {type(e).__name__}: {e}")
        if resp.status_code in (403, 429):
            raise KayakBlocked(f"HTTP {resp.status_code} for autocomplete")
        if resp.status_code == 400:
            raise KayakBadRequest(resp.text[:200])
        if resp.status_code != 200:
            raise KayakUpstreamError(f"HTTP {resp.status_code} for autocomplete")
        try:
            payload = resp.json()
        except Exception:
            raise KayakBlocked(f"non-JSON autocomplete response: {resp.text[:120]}")
        if not isinstance(payload, list):
            raise KayakUpstreamError(f"unexpected autocomplete payload: {resp.text[:120]}")
        return payload
    return _retrying(lambda: _on_session(once))
