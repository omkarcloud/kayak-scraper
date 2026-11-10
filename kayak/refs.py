"""Reference resolvers + the small slug tables for /kayak/*.

ONE param per input (tripadvisor QueryOrIdField convention): `hotel`
accepts a bare KAYAK hotel id (61867) OR any kayak.* link that carries it:

  * the hotel's SEO page   https://www.kayak.com/Miami-Hotels-Miami-International-Airport-Hotel.61867.ksp
  * a slug-less page       https://www.kayak.com/x.61867.ksp  (the site 301s to the canonical slug)
  * a results-page detail  https://www.kayak.com/hotels/Miami-International-Airport-Hotel,Miami-p53912-h61867-details/2026-12-20/2026-12-22/2adults
  * an API-style link      https://www.kayak.com/...?hid=61867

Resolvers raise ValueError with a user-facing message (RefField -> 400).
"""
import re
from urllib.parse import parse_qs, urlparse

SITE = "https://www.kayak.com"
CDN = "https://content.r9cdn.net"

HID_RE = re.compile(r"^[0-9]{1,12}$")
_LINK_KSP_RE = re.compile(r"\.([0-9]{1,12})\.ksp(?:$|[?#/])", re.I)
_LINK_DETAILS_RE = re.compile(r"-h([0-9]{1,12})(?:-|/|$|\?)")


def _host_is_kayak(url):
    host = (urlparse(url).hostname or "").lower()
    return host == "kayak.com" or ".kayak." in f".{host}" or host.startswith("kayak.")


def resolve_hotel(value):
    """Bare hotel id or a kayak.* hotel link -> the hotel id (string)."""
    value = (value or "").strip()
    if HID_RE.match(value):
        return value
    if value.startswith(("http://", "https://", "//")):
        url = value if not value.startswith("//") else "https:" + value
        if not _host_is_kayak(url):
            raise ValueError("Must be a kayak.com link.")
        match = _LINK_KSP_RE.search(url) or _LINK_DETAILS_RE.search(urlparse(url).path)
        if match:
            return match.group(1)
        hid = parse_qs(urlparse(url).query).get("hid", [None])[0]
        if hid and HID_RE.match(hid):
            return hid
        raise ValueError("Must be a kayak.com hotel link "
                         "(https://www.kayak.com/<City>-Hotels-<Name>.<id>.ksp).")
    raise ValueError("Must be a KAYAK hotel id (61867) or a kayak.com hotel link.")


def hotel_link(hid, slug=None):
    """The hotel's page link. Without the SEO slug the site 301s
    /<anything>.<id>.ksp to the canonical slug, so a bare id still opens."""
    return f"{SITE}/{slug or 'Hotel'}.{hid}.ksp"


def hotel_page_path(hid):
    return f"/Hotel.{hid}.ksp"


# ---- autocomplete ---------------------------------------------------------------------
# /mvm/smartyv2/search: `s` is the smarty search type and `vertical` the
# form it serves. Measured 2026-11-07 (same answers from a US datacenter exit
# and an Indian IP; always 6 rows, no count param):
#   s=50 vertical=hotels   cities, neighbourhoods, landmarks, regions, airports
#                          and hotels — the stays form's mix ("las vegas" ->
#                          Las Vegas NV city first)
#   s=58 vertical=flights  airports + metro areas (s=58 is the airport picker:
#                          "las vegas" -> LAS + BLD only, a city with no
#                          airport -> its nearest airports, loctype "apnc")
#   s=81 vertical=cars     airports + cities (the car-rental pick-up mix)
# `searchHotels=true` changes nothing, so "hotels" is the stays answer with
# only its hotel rows kept (HOTELS_ONLY), for looking up a hotel id by name.
LOCATION_TYPES = {
    "stays": {"s": "50", "vertical": "hotels"},
    "hotels": {"s": "50", "vertical": "hotels"},
    "flights": {"s": "58", "vertical": "flights"},
    "cars": {"s": "81", "vertical": "cars"},
}
HOTELS_ONLY = "hotels"

# smarty `loctype` -> public type (every loctype seen 2026-11-07; an unknown
# one passes through as is)
LOCTYPE = {
    "city": "city", "ap": "airport", "apnc": "airport", "hotel": "hotel",
    "lm": "landmark", "hood": "neighborhood", "ctry": "country",
    "reg": "region", "freereg": "region", "rail": "rail_station",
}

# ---- reviews ----------------------------------------------------------------------------
# /i/api/seo/reviews/v3/filtered params the site honours (2026-11-07 live
# checks; `order`, `provider`, `seasons`, `ratingBuckets` are client-side
# state that the endpoint ignores):
#   sortType       recent | oldest | scoreDesc | scoreAsc  (ApiReviewSortType in the bundle)
#   travelerTypes  comma list of families | couples | solo | friends
#   scoresRanges   "min-max" on the site's 0-100 scale (several ranges comma-joined)
#   searchText     free text
#   tagClusterName one of the hotel's review tags ("great location")
REVIEW_SORTS = {"recent": "recent", "oldest": "oldest", "highest": "scoreDesc", "lowest": "scoreAsc"}
TRAVELLER_TYPES = ("families", "couples", "solo", "friends")
REVIEWS_PAGE_SIZE = 10   # the endpoint rejects amount > 10 ("must be less than or equal to 10")
