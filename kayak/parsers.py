"""Raw KAYAK pages / JSON -> clean dicts for every /kayak/* endpoint. Pure
functions, no I/O.

Sources (kayak/fetch.py):
  * the hotel SEO page's inline React state (`<script id="jsonData_R9DataStorage">`):
    serverData.contentState (amenities, photos, map POIs, nearby hotels,
    FAQs / tips, review summary, score distributions, price charts),
    serverData.HotelDetailsData (room rows x provider offers for the site's
    default stay), serverData.meta + locale
  * /i/api/search/v1/static/hotels/details  (overview, policies, photos,
    geolocation, nearby transport, amenities, freebies)
  * /i/api/seo/reviews/v3/filtered           (reviews)
  * /i/api/seo/reviews/v1/reviewsWithScores  (score summary; empty 200 = no reviews)
  * /i/api/seo/reviewTags/v1/hotel/tags      (AI topic tags + AI summary)
  * /i/api/seo/reviews/v3/hotelScoreDistributionBySource
  * /mvm/smartyv2/search                     (autocomplete)

Value conventions (shared with the other scraper packages):
  * scores   KAYAK stores review scores on a 0-100 scale and displays them
             /10 ("6.6"); every score here is the displayed 0-10 number
  * dates    review month "Nov 2026" -> "2026-11"; stay dates stay ISO
  * money    {"amount": 132.56, "currency": "USD", "text": "$133"}
  * links    absolute: pages on www.kayak.com, images / logos on content.r9cdn.net;
             review source links are unwrapped from KAYAK's /out?url= redirect
  * keys     snake_case; `link` not `url`; booleans as questions; absent = null

Fixtures captured 2026-11-07 (kayak/fixtures/): the Miami International
Airport Hotel page (rich: 19 provider groups, 3 charts, AI tags), the
Basecamp Spitsbergen page (no cheapest-time-to-book chart, one review
source), the site's 404 page, static details for the Miami hotel, for an
apartment WITHOUT an SEO page (Bed & Breakfast Sandavagur) and for a guest
house with zero reviews, review pages / scores / tags / sources for the
same hotels, and smarty lists for the four location types (recaptured
2026-11-07 after the smarty search-type fix). The two hotel pages are
trimmed (2026-11-10) to their <title> and the inline state minus what no
parser reads (the UI translation table, feature flags, asset lists, the
error reporter's config): 2.2 MB -> 280 KB.
"""
import html as html_lib
import json
import re
from urllib.parse import parse_qs, urlparse

from kayak.refs import CDN, LOCTYPE, SITE, hotel_link

_R9_RE = re.compile(r'<script[^>]+id="jsonData_R9DataStorage"[^>]*>(.*?)</script>', re.S)
_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_SLUG_RE = re.compile(r"/([^/]+)\.(\d+)\.ksp")


# ---- helpers ----------------------------------------------------------------------------

def _clean(value):
    """Collapse whitespace; "" / placeholder -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = _WS_RE.sub(" ", str(value)).strip()
    return text if text and text not in ("-", "N/A", "null", "None") else None


def _text(value):
    """HTML fragment -> plain text (tags stripped, entities decoded)."""
    if value is None:
        return None
    return _clean(html_lib.unescape(_TAG_RE.sub(" ", str(value))))


def _num(value):
    """'6,228' / '3.0' / 3 -> number; junk -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    return int(number) if number.is_integer() and "." not in match.group(0) else number


def _int(value):
    number = _num(value)
    return int(number) if number is not None else None


parse_number = _num


def _id(value):
    """KAYAK ids arrive as strings on pages and as ints in the API: always a string."""
    text = _clean(value)
    return str(text) if text is not None else None


def _score10(value):
    """A KAYAK 0-100 score -> the displayed 0-10 number (66 -> 6.6)."""
    number = _num(value)
    if number is None:
        return None
    return round(number / 10.0, 1)


def _month_year(value):
    """'Nov 2026' -> '2026-11' (en-us month names); anything else as text."""
    text = _clean(value)
    if not text:
        return None
    parts = text.split()
    if len(parts) == 2 and parts[0][:3].lower() in _MONTHS and parts[1].isdigit():
        return f"{parts[1]}-{_MONTHS[parts[0][:3].lower()]:02d}"
    return text


def _site_link(path):
    text = _clean(path)
    if not text:
        return None
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("http"):
        return text
    return SITE + (text if text.startswith("/") else "/" + text)


def _cdn_link(path):
    """Image / logo path -> absolute content.r9cdn.net link ('/rimg/..' and
    '/provider-logos/..' both live under /rimg on the CDN)."""
    text = _clean(path)
    if not text:
        return None
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("http"):
        return text
    if text.startswith("/provider-logos/"):
        text = "/rimg" + text
    return CDN + (text if text.startswith("/") else "/" + text)


def _unwrap_out(link):
    """KAYAK's /out?url=<encoded target>&trackClickOut=... -> the target."""
    text = _clean(link)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.path.rstrip("/") == "/out":
        target = parse_qs(parsed.query).get("url", [None])[0]
        if target:
            return target
    return text


def _coords(point):
    if not isinstance(point, dict):
        return None
    lat, lng = _num(point.get("lat")), _num(point.get("lng"))
    if lat is None or lng is None:
        return None
    return {"lat": lat, "lng": lng}


def _money(block):
    if not isinstance(block, dict):
        return None
    amount = _num(block.get("price"))
    if amount is None:
        return None
    return {"amount": amount, "currency": _clean(block.get("currency")), "text": _clean(block.get("localizedPrice"))}


def _bool(value):
    return value if isinstance(value, bool) else (None if value is None else str(value).lower() == "true")


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _slug_of(path):
    match = _SLUG_RE.search(path or "")
    return match.group(1) if match else None


# ---- the hotel SEO page -----------------------------------------------------------------

def page_state(html):
    """The inline React state of a frontier page, or None when the page
    carries none / is the site's 404 page."""
    if not html:
        return None
    title = _TITLE_RE.search(html)
    if title and "page not found" in title.group(1).lower():
        return None
    match = _R9_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def _named(items, name_key="localizedName", code_key="code"):
    out = []
    for item in _list(items):
        if isinstance(item, dict):
            name = _clean(item.get(name_key))
            if name:
                out.append({"code": _clean(item.get(code_key)), "name": name})
        elif _clean(item):
            out.append({"code": None, "name": _clean(item)})
    return out


def _amenities(block, categories_key):
    block = _dict(block)
    top = [a["name"] for a in _named(block.get("topAmenities"))]
    categories = []
    for cat in _list(block.get(categories_key)):
        if not isinstance(cat, dict):
            continue
        categories.append({
            "code": _clean(cat.get("code")),
            "name": _clean(cat.get("localizedName")),
            "amenities": _named(cat.get("amenities")),
        })
    count = _int(block.get("count"))
    if count is None:
        count = sum(len(c["amenities"]) for c in categories) or None
    return {"count": count, "top": top, "categories": categories}


def _info_rows(items):
    """policies / goodToKnow rows: {type, title, dataText, description, additionalInfo}."""
    out = []
    for row in _list(items):
        if not isinstance(row, dict):
            continue
        out.append({
            "type": _clean(row.get("type")),
            "title": _clean(row.get("title")),
            "text": _text(row.get("dataText")),
            "description": _text(row.get("description")),
            "note": _text(row.get("additionalInfo") or row.get("tooltipInfo")),
        })
    return out


def _qa(items, q="question", a="answer"):
    out = []
    for row in _list(items):
        if isinstance(row, dict) and _clean(row.get(q)):
            out.append({"question": _text(row.get(q)), "answer": _text(row.get(a))})
    return out


def _nearby_hotel(row):
    row = _dict(row)
    hid = _id(row.get("hotelId"))
    price_usd = _num(row.get("priceUsd"))
    return {
        "id": hid,
        "name": _clean(row.get("name")),
        "link": _site_link(row.get("url")) or (hotel_link(hid) if hid else None),
        "classification": _clean(row.get("classificationDisplayName")),
        "rating": {
            "score": _num(row.get("ratingScore")),
            "text": _clean(row.get("ratingText")),
            "review_count": _int(row.get("reviewCount")),
        },
        "distance": {"miles": _num(row.get("distanceMiles")), "text": _clean(row.get("distance"))},
        "price": {"amount": price_usd, "currency": "USD" if price_usd is not None else None,
                  "text": _clean(row.get("price"))},
        "top_amenities": [a["name"] for a in _named(row.get("topAmenities"))],
        "is_hotel": _bool(row.get("isHotel")),
        "is_rental": _bool(row.get("isRental")),
    }


def _sentiments(items):
    out = []
    for row in _list(items):
        if isinstance(row, dict) and _clean(row.get("sentiment")):
            out.append({"text": _clean(row.get("sentiment")), "count": _int(row.get("count")),
                        "examples": [_clean(x) for x in _list(row.get("additionalSentiments")) if _clean(x)]})
    return out


def _ai_tags(items):
    out = []
    for row in _list(items):
        if not isinstance(row, dict):
            continue
        out.append({
            "name": _clean(row.get("localizedName")) or _clean(row.get("name")),
            "code": _clean(row.get("name")),
            "sentiment": _clean(row.get("sentiment")),
            "score": _num(row.get("score")),
            "review_count": len(_list(row.get("reviewIds"))) or None,
        })
    return out


def _by_source(items):
    out = []
    for row in _list(items):
        if not isinstance(row, dict):
            continue
        src = _dict(row.get("reviewSource"))
        out.append({
            "source": {"id": _clean(src.get("providerId")), "name": _clean(src.get("providerName")),
                       "logo": _cdn_link(src.get("providerLogo"))},
            "review_count": _int(row.get("count")),
            "total_count": _int(row.get("totalCount")),
            "average_score": _score10(row.get("avgScore")),
        })
    return out


def _score_distribution(items):
    out = []
    for row in _list(items):
        if not isinstance(row, dict):
            continue
        bucket = _dict(row.get("ratingBucket"))
        lo, hi = _score10(bucket.get("min")), _num(bucket.get("max"))
        out.append({"min_score": lo, "max_score": _score10(min(hi, 100)) if hi is not None else None,
                    "review_count": _int(row.get("count"))})
    return out


def review_summary(data, ai_tags=None, ai_summary=None, distribution=None, by_source=None):
    """The shared review-summary shape from reviewsWithScores (API) or
    contentState.reviewsData (page) plus the optional extras."""
    data = _dict(data)
    if not data and not by_source:
        return None
    return {
        "score": _score10(data.get("overallScore")),
        "review_count": _int(data.get("totalReviewAmount")),
        "score_by_traveller_type": {k: _score10(v) for k, v in _dict(data.get("scoreByTravellerType")).items()} or None,
        "review_count_by_traveller_type": {k: _int(v) for k, v in _dict(data.get("reviewCountByTravellerType")).items()} or None,
        "pros": _sentiments(data.get("prosSentimentsWithCount")),
        "cons": _sentiments(data.get("consSentimentsWithCount")),
        "tags": [{"tag": _clean(t.get("tag")), "count": _int(t.get("count"))}
                 for t in _list(data.get("reviewTags")) if isinstance(t, dict) and _clean(t.get("tag"))],
        "ai_tags": _ai_tags(ai_tags if ai_tags is not None else data.get("aiReviewTags")),
        "ai_summary": _clean(ai_summary if ai_summary is not None else data.get("aiReviewSummary")),
        "score_distribution": _score_distribution(distribution) if distribution is not None else None,
        "by_source": _by_source(by_source) if by_source is not None else None,
    }


def _chart(block):
    block = _dict(block)
    values, labels = _list(block.get("values")), _list(block.get("labels"))
    if not values:
        return None
    faq = _dict(block.get("faq"))
    return {"points": [{"label": _clean(l), "price": _num(v)} for l, v in zip(labels, values)],
            "advice": _text(faq.get("answer")), "note": _text(block.get("tooltip"))}


def _rates(hd):
    """HotelDetailsData -> the rates slice (None when the page carries none)."""
    hd = _dict(hd)
    rates = _dict(_dict(hd.get("rates")).get("rates"))
    groups = _list(rates.get("groups"))
    form = _dict(hd.get("ratesFormData"))
    providers, cheapest, currency = [], None, None
    for group in groups:
        if not isinstance(group, dict):
            continue
        rooms, logo, code = [], None, None
        for row in _list(group.get("rows")):
            if not isinstance(row, dict):
                continue
            options = []
            for opt in _list(row.get("bookingOptions")):
                if not isinstance(opt, dict):
                    continue
                price, total = _money(opt.get("price")), _money(opt.get("totalPrice"))
                code = code or _clean(opt.get("providerCode"))
                logo = logo or _cdn_link(opt.get("logo"))
                beds = {k: _int(v) for k, v in _dict(opt.get("bedCounts")).items()
                        if k != "noBedType" and _int(v)}
                unspecified = _int(_dict(opt.get("bedCounts")).get("noBedType"))
                if unspecified:
                    beds["unspecified"] = unspecified
                options.append({
                    "price": price,
                    "total_price": total,
                    "rate_type": _clean(opt.get("rateType")),
                    "beds": beds or None,
                    "freebies": [f["name"] for f in _named(opt.get("freebies"))],
                    "is_private_deal": _bool(opt.get("privateDeal")),
                    "is_locked_deal": _bool(opt.get("lockedDeal")),
                    "booking_link": _site_link(opt.get("bookingUrl")),
                })
                if price:
                    currency = currency or price["currency"]
                    if cheapest is None or price["amount"] < cheapest["amount"]:
                        cheapest = {"amount": price["amount"], "currency": price["currency"],
                                    "provider": _clean(opt.get("localizedProviderName")) or _clean(group.get("localizedTitle")),
                                    "room": _clean(row.get("localizedDescription"))}
            rooms.append({"description": _clean(row.get("localizedDescription")), "options": options})
        providers.append({
            "provider": {"code": code, "name": _clean(group.get("localizedTitle")), "logo": logo},
            "has_other_deals": _bool(group.get("otherDeals")),
            "rooms": rooms,
        })
    if not providers and not form:
        return None
    check_in, check_out = _clean(form.get("startDate")), _clean(form.get("endDate"))
    nights = None
    if check_in and check_out:
        try:
            from datetime import date
            nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
        except ValueError:
            nights = None
    return {
        "stay": {"check_in": check_in, "check_out": check_out, "nights": nights,
                 "adults": _int(form.get("numAdults")), "rooms": _int(form.get("numRooms"))},
        "currency": currency,
        "cheapest": cheapest,
        "providers": providers,
    }


def parse_hotel_page(html):
    """The hotel SEO page -> the page record, or None for the site's 404
    page / a page without the inline state."""
    state = page_state(html)
    if not state:
        return None
    sd = _dict(state.get("serverData"))
    cs = _dict(sd.get("contentState"))
    if not cs or _bool(cs.get("isHotelValid")) is False:
        return None
    schema = _dict(cs.get("hotelSchema"))
    address = _dict(schema.get("address"))
    form = _dict(cs.get("searchFormContainerData"))
    meta = _dict(sd.get("meta"))
    canonical = _clean(meta.get("canonical")) or _clean(_dict(sd.get("global")).get("canonical"))
    hid = _id(cs.get("hotelId")) or _id(_dict(_dict(state.get("props")).get("reqParams")).get("id"))
    breadcrumbs = [b for b in _list(cs.get("breadcrumbs")) if isinstance(b, dict)]
    city_crumb = breadcrumbs[-2] if len(breadcrumbs) >= 2 else {}
    rating = _dict(schema.get("aggregateRating"))
    gallery = _dict(cs.get("photoGalleryData"))
    nearby = _dict(cs.get("nearbyHotelsData"))
    map_state = _dict(_dict(cs.get("locationData")).get("mapState"))
    home = _dict(map_state.get("home"))
    charts = _dict(cs.get("groupedCharts"))
    good_to_know = _info_rows(cs.get("goodToKnowData"))
    hotel_price_usd = _num(nearby.get("priceUsd"))
    return {
        "id": hid,
        "name": _clean(schema.get("name")) or _clean(form.get("hotelName")),
        "link": canonical or (hotel_link(hid) if hid else None),
        "slug": _slug_of(canonical or ""),
        "alternate_names": [_clean(n) for n in _list(schema.get("alternateName")) if _clean(n)],
        "classification_code": _clean(form.get("hotelClassificationCode")),
        "stars": _num(schema.get("starRating")) if _bool(form.get("useStarRating")) is not False else None,
        "description": _text(schema.get("description")),
        "about": _text(cs.get("hotelDescription") or _dict(cs.get("aboutSectionData")).get("hotelDescription")),
        "licence_info": _clean(_dict(cs.get("aboutSectionData")).get("localizedLicenseInfo")),
        "official_website": _clean(cs.get("officialWebsite")),
        "phone": _clean(schema.get("telephone")) or _clean(form.get("phone")),
        "address": {
            "full": _text(form.get("shortAddress")) or _text(home.get("address")),
            "street": _clean(address.get("streetAddress")),
            "city": _clean(address.get("addressLocality")),
            "region": _clean(address.get("addressRegion")),
            "postal_code": _clean(address.get("postalCode")),
            "country": _clean(address.get("addressCountry")),
            "country_code": _clean(form.get("countryCode")),
        },
        "coordinates": _coords(home.get("coordinates")) or _coords(nearby.get("location")),
        "city": {"id": _id(cs.get("cityId")), "name": _clean(cs.get("cityName")),
                 "link": _site_link(city_crumb.get("href")) if _clean(city_crumb.get("href")) not in (None, "/") else None},
        "price_range": _clean(schema.get("priceRange")),
        "latest_price": {"amount": hotel_price_usd, "currency": "USD"} if hotel_price_usd is not None else None,
        "rating": {"score": _num(rating.get("ratingValue")), "best_score": _num(rating.get("bestRating")),
                   "review_count": _int(rating.get("ratingCount"))},
        "policies": _info_rows(cs.get("policies")),
        "good_to_know": good_to_know,
        "amenities": _amenities(cs.get("amenitiesData"), "categorisedAmenities"),
        "amenity_names": [_clean(a) for a in _list(schema.get("amenityFeature")) if _clean(a)],
        "photos": [{
            "id": _clean(p.get("imageId")),
            "link": _cdn_link(p.get("imageSrc")),
            "thumbnail_link": _cdn_link(p.get("thumbnailSrc")),
            "category": _clean(p.get("localizedCategory")),
            "alt_text": _clean(p.get("altText")),
            "source": _clean(p.get("source")),
            "attribution": _clean(p.get("attribution")),
        } for p in _list(gallery.get("hotelPhotos")) if isinstance(p, dict)],
        "photo_categories": [_clean(c.get("localizedCategory")) for c in _list(gallery.get("categoryList"))
                             if isinstance(c, dict) and _clean(c.get("localizedCategory"))],
        "review_sentiments": [_clean(s) for s in _list(gallery.get("commonReviewSentiment")) if _clean(s)],
        "cover_image": _cdn_link(cs.get("coverImageUrl")),
        "nearby_places": [{
            "id": _id(p.get("locationId")),
            "name": _clean(p.get("name")),
            "distance": _clean(p.get("distance")),
            "coordinates": _coords(p.get("coordinates")),
        } for p in _list(map_state.get("locations")) if isinstance(p, dict) and _clean(p.get("name"))],
        "faqs": _qa(cs.get("faqs")),
        "ai_faqs": _qa(cs.get("faqsAi"), "header", "content"),
        "tips": [_text(t) for t in _list(cs.get("tips")) if _text(t)],
        "ai_tips": [{"title": _text(t.get("header")), "text": _text(t.get("content"))}
                    for t in _list(cs.get("tipsAi")) if isinstance(t, dict)],
        "reviews": review_summary(cs.get("reviewsData"), distribution=cs.get("reviewsScoreDistribution"),
                                  by_source=cs.get("reviewsScoreDistributionBySource")),
        "rates": _rates(sd.get("HotelDetailsData")),
        "nearby_hotels": {
            "closest": [_nearby_hotel(h) for h in _list(nearby.get("closestNearbyHotels"))],
            "cheapest": [_nearby_hotel(h) for h in _list(nearby.get("cheapestNearbyHotels"))],
            "most_recommended": [_nearby_hotel(h) for h in _list(nearby.get("mostRecommendedNearbyHotels"))],
        } if nearby else None,
        "price_charts": {
            "cheapest_time_to_book": _chart(charts.get("cheapestTimeToBook")),
            "monthly": _chart(charts.get("monthlyStayPrice")),
            "weekly": _chart(charts.get("weeklyStayPrice")),
        },
        "currency": _clean(_dict(_dict(sd.get("locale")).get("currency")).get("code")),
        "meta": {"title": _clean(meta.get("title")), "description": _clean(meta.get("description")),
                 "image": _cdn_link(meta.get("ogImage")), "rendered_at": _clean(sd.get("renderDate"))},
    }


# ---- static details API -----------------------------------------------------------------

def parse_static_details(data):
    """/i/api/search/v1/static/hotels/details -> clean dict (None for an
    empty / unknown payload)."""
    data = _dict(data)
    overview = _dict(data.get("overview"))
    if not overview:
        return None
    geo = _dict(data.get("geolocation"))
    classification = _dict(overview.get("hotelClassification"))
    hid = _id(overview.get("hotelId"))
    distance = _num(geo.get("distanceFromCenter"))
    return {
        "id": hid,
        "name": _clean(overview.get("localizedHotelName")),
        "local_name": _clean(overview.get("localHotelName")),
        "classification": {"code": _clean(classification.get("code")),
                           "name": _clean(classification.get("localizedName"))} if classification else None,
        "stars": _num(overview.get("stars")) if _bool(overview.get("useStars")) is not False else None,
        "check_in_time": _clean(overview.get("checkin")),
        "check_out_time": _clean(overview.get("checkout")),
        "currency": _clean(overview.get("currency")),
        "address": _clean(overview.get("localizedAddress")),
        "city": _clean(overview.get("localizedCityName")) or _clean(geo.get("localizedCity")),
        "country_code": _clean(overview.get("countryCode")),
        "phone": _clean(overview.get("phone")),
        "description": _text(overview.get("localizedDescription")),
        "description_source": _clean(overview.get("descriptionAttribution")),
        "property_description": _text(overview.get("localizedPropertyDescription")),
        "policies": [{"code": _clean(p.get("code")), "title": _clean(p.get("localizedTitle")),
                      "text": _text(p.get("localizedDescription"))}
                     for p in _list(overview.get("policies")) if isinstance(p, dict)],
        "highlights": [{"code": _clean(h.get("code")), "title": _clean(h.get("localizedTitle")),
                        "text": _text(h.get("localizedDescription"))}
                       for h in _list(overview.get("highlights")) if isinstance(h, dict)],
        "coordinates": _coords(geo.get("point")),
        "distance_from_center": {"value": round(distance, 2), "unit": _clean(geo.get("distanceUnits")),
                                 "text": _clean(geo.get("localizedDisplayDistance"))} if distance is not None else None,
        "nearby_landmarks": [_transport(t) for t in _list(data.get("nearbyLandmarks"))],
        "nearby_transport": [_transport(t) for t in _list(data.get("nearbyTransport"))],
        "amenities": _amenities(data.get("amenities"), "categories"),
        "freebies": [{"code": _clean(f.get("code")), "name": _clean(f.get("localizedName")),
                      "category": _clean(f.get("localizedCategory"))}
                     for f in _list(data.get("freebies")) if isinstance(f, dict)],
        "photos": [{
            "link": _cdn_link(p.get("imageSrc")),
            "thumbnail_link": _cdn_link(p.get("thumbnailSrc")),
            "category": _clean(p.get("localizedCategory")),
            "source": _clean(p.get("source")),
            "attribution": _clean(p.get("attribution")),
        } for p in _list(data.get("photos")) if isinstance(p, dict)],
        "static_map_link": _clean(_dict(data.get("staticMapImage")).get("url")),
    }


def _transport(row):
    row = _dict(row)
    distance = _num(row.get("distanceFromHotel"))
    return {
        "id": _id(row.get("id")),
        "name": _clean(row.get("localizedName")),
        "type": _clean(row.get("transportType")) or _clean(row.get("type")),
        "distance": {"value": round(distance, 2), "unit": _clean(row.get("distanceUnits")),
                     "text": _clean(row.get("localizedDistanceFromHotel"))} if distance is not None else None,
        "duration_minutes": _int(row.get("durationMinutes")),
        "coordinates": _coords(row.get("location")),
    }


# ---- reviews ------------------------------------------------------------------------------

def parse_review(row):
    row = _dict(row)
    return {
        "id": _clean(row.get("id")),
        "date": _month_year(row.get("localizedMonthYear")),
        "score": _score10(row.get("score")),
        "rating_text": _clean(row.get("localizedRatingCategory")),
        "comment": _text(row.get("genericComment")),
        "positive": _text(row.get("positiveComment")),
        "negative": _text(row.get("negativeComment")),
        "author": _clean(row.get("author")),
        "source": {"name": _clean(row.get("siteName")), "link": _unwrap_out(row.get("siteLink")),
                   "logo": _cdn_link(row.get("siteLogo"))},
        "is_kayak_review": _bool(row.get("internal")),
    }


def parse_reviews(data):
    """/i/api/seo/reviews/v3/filtered -> {"total_count", "reviews"}."""
    data = _dict(data)
    return {"total_count": _int(data.get("reviewCount")) or 0,
            "reviews": [parse_review(r) for r in _list(data.get("reviews")) if isinstance(r, dict)]}


def parse_review_tags(data):
    """/i/api/seo/reviewTags/v1/hotel/tags -> (ai_tags raw list, summary)."""
    tags = _list(_dict(data).get("hotelTags"))
    first = _dict(tags[0]) if tags else {}
    return _list(first.get("standardTags")), _clean(first.get("reviewsSummary"))


def parse_score_by_source(data):
    return _list(_dict(data).get("distributions"))


# ---- the merged hotel record -----------------------------------------------------------

def merge_hotel_record(hid, page, static, scores=None, tags=None, by_source=None):
    """ONE record per hotel from the page (may be None: small properties
    have no SEO page) and the static details API (+ the review API trio
    when there is no page). The endpoint slices read from it."""
    page = page or {}
    static = static or {}
    if page.get("reviews") is not None:
        reviews = page["reviews"]
    else:
        ai_tags, ai_summary = parse_review_tags(tags) if tags is not None else (None, None)
        reviews = review_summary(scores, ai_tags=ai_tags, ai_summary=ai_summary,
                                 by_source=parse_score_by_source(by_source) if by_source is not None else None)
    classification = static.get("classification") or (
        {"code": page.get("classification_code"), "name": None} if page.get("classification_code") else None)
    page_address = page.get("address") or {}
    return {
        "id": hid,
        "name": page.get("name") or static.get("name"),
        "link": page.get("link") or hotel_link(hid),
        "has_page": bool(page),
        "alternate_names": page.get("alternate_names") or [],
        "classification": classification,
        "stars": page.get("stars") if page.get("stars") is not None else static.get("stars"),
        "description": static.get("description") or page.get("description"),
        "description_source": static.get("description_source"),
        "about": page.get("about") or static.get("property_description"),
        "licence_info": page.get("licence_info"),
        "official_website": page.get("official_website"),
        "phone": page.get("phone") or static.get("phone"),
        "check_in_time": static.get("check_in_time"),
        "check_out_time": static.get("check_out_time"),
        "address": {
            "full": page_address.get("full") or static.get("address"),
            "street": page_address.get("street"),
            "city": page_address.get("city") or static.get("city"),
            "region": page_address.get("region"),
            "postal_code": page_address.get("postal_code"),
            "country": page_address.get("country"),
            "country_code": page_address.get("country_code") or static.get("country_code"),
        },
        "coordinates": static.get("coordinates") or page.get("coordinates"),
        "distance_from_center": static.get("distance_from_center"),
        "city": page.get("city") or {"id": None, "name": static.get("city"), "link": None},
        "currency": page.get("currency") or static.get("currency"),
        "price_range": page.get("price_range"),
        "latest_price": page.get("latest_price"),
        "rating": page.get("rating") or ({"score": reviews.get("score"), "best_score": 10,
                                           "review_count": reviews.get("review_count")} if reviews else None),
        "policies": page.get("policies") or [],
        "policy_notes": static.get("policies") or [],
        "highlights": static.get("highlights") or [],
        "good_to_know": page.get("good_to_know") or [],
        "amenities": page.get("amenities") or static.get("amenities"),
        "freebies": static.get("freebies") or [],
        "photos": page.get("photos") or static.get("photos") or [],
        "photo_categories": page.get("photo_categories") or [],
        "cover_image": page.get("cover_image") or ((static.get("photos") or [{}])[0].get("link") if static.get("photos") else None),
        "nearby_places": page.get("nearby_places") or [],
        "nearby_landmarks": static.get("nearby_landmarks") or [],
        "nearby_transport": static.get("nearby_transport") or [],
        "static_map_link": static.get("static_map_link"),
        "faqs": page.get("faqs") or [],
        "ai_faqs": page.get("ai_faqs") or [],
        "tips": page.get("tips") or [],
        "ai_tips": page.get("ai_tips") or [],
        "review_sentiments": page.get("review_sentiments") or [],
        "reviews": reviews,
        "rates": page.get("rates"),
        "nearby_hotels": page.get("nearby_hotels"),
        "price_charts": page.get("price_charts") or {"cheapest_time_to_book": None, "monthly": None, "weekly": None},
        "meta": page.get("meta"),
    }


# ---- autocomplete -----------------------------------------------------------------------

def parse_location(row):
    row = _dict(row)
    loctype = _clean(row.get("loctype")) or _clean(row.get("kayakType"))
    hid = _id(row.get("hid")) if loctype == "hotel" else None
    images = _dict(row.get("destination_images"))
    box = [_num(row.get(k)) for k in ("box_minY", "box_minX", "box_maxY", "box_maxX")]
    return {
        "id": _id(row.get("id")),
        "name": _clean(row.get("displayname")) or _clean(row.get("smartyDisplay")),
        "short_name": _clean(row.get("shortdisplayname")) or _clean(row.get("name")),
        "type": LOCTYPE.get(loctype, loctype),
        "link": hotel_link(hid) if hid else None,
        "hotel_id": hid,
        "airport_code": _clean(row.get("apicode")) or _clean(row.get("ap")),
        "airport_name": _clean(row.get("airportname")),
        "place_id": _id(row.get("placeID")),
        "city": {"id": _id(row.get("ctid")), "name": _clean(row.get("cityonly")) or _clean(row.get("cityname")),
                 "code": _clean(row.get("cityCode"))},
        "region": {"id": _id(row.get("rid")), "code": _clean(row.get("rc")), "name": _clean(row.get("region"))},
        "subregion": _clean(row.get("subregion")),
        "country": {"id": _id(row.get("cid")), "code": _clean(row.get("cc")), "name": _clean(row.get("country"))},
        "coordinates": _coords(row),
        "bounding_box": {"south": box[0], "west": box[1], "north": box[2], "east": box[3]}
        if all(v is not None for v in box) else None,
        "timezone": _clean(row.get("timezone")),
        "utc_offset": _clean(row.get("utc")),
        "image": _clean(images.get("image_jpeg")) or _clean(images.get("image_webp")),
        "guidebook_count": _int(row.get("guidebook_count")),
        "is_metro_only": _bool(row.get("isMetroOnly")),
    }


def parse_locations(data):
    return [parse_location(r) for r in _list(data) if isinstance(r, dict) and (_clean(r.get("displayname")) or _clean(r.get("id")))]
