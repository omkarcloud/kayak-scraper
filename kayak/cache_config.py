"""Cache TTL per /kayak/* endpoint (cache.py, keyed on the validated params).
The four hotel slices (details / rates / nearby / price-insights) share ONE
cached record (api._record): the SEO page + the static details JSON are
fetched once per hotel and sliced per endpoint.
"""
from datetime import timedelta

# The hotel SEO page is itself served from KAYAK's seo-cache (its render
# date was hours old on 2026-11-07) and the rates on it are the site's own
# snapshot for a default stay a week out, so 6 h never adds staleness the
# site does not already have.
HOTEL_CACHE = timedelta(hours=6)
# Reviews arrive a few a day per hotel; the first page of "recent" moves
# fastest, deeper pages hardly at all.
REVIEWS_CACHE = timedelta(hours=12)
# Autocomplete: places / airports / hotel names change slowly.
LOCATIONS_CACHE = timedelta(days=7)
