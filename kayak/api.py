"""The /kayak/* endpoint functions (route_glue's route_table calls them with
the schema's loaded kwargs).

The four hotel slices (details / rates / nearby / price-insights) read ONE
cached record: cache.cached_call stores the merged parse (SEO page + static
details JSON, or the static details + review API trio for a hotel without
a page) under kayak.hotel keyed on the hotel id, so hitting all four on the
same hotel costs one round of upstream fetches. The slices do not overlap
(details carries counts where the others carry the lists).
"""
import math

from cache import cached_call
from kayak import cache_config as ttl
from kayak import parsers
from kayak.fetch import (KayakNotFound, fetch_hotel_page, fetch_locations, fetch_review_scores,
                         fetch_review_tags, fetch_reviews, fetch_score_by_source, fetch_static_details)
from kayak.refs import HOTELS_ONLY, REVIEWS_PAGE_SIZE


# ---- the shared hotel record ---------------------------------------------------------------

def _hotel_record(hotel):
    """Page + static details; a hotel the site has no SEO page for (small
    properties) comes from the static API plus the three review-summary
    routes. An unknown id is the static API's own 404."""
    page = parsers.parse_hotel_page(fetch_hotel_page(hotel))
    static = parsers.parse_static_details(fetch_static_details(hotel))
    if page is None and static is None:
        raise KayakNotFound(f"hotel {hotel} not found")
    scores = tags = by_source = None
    if page is None:
        scores = fetch_review_scores(hotel)
        tags = fetch_review_tags(hotel)
        by_source = fetch_score_by_source(hotel)
    return parsers.merge_hotel_record(hotel, page, static, scores, tags, by_source)


def _record(hotel):
    return cached_call("kayak.hotel", {"hotel": hotel}, _hotel_record, ttl.HOTEL_CACHE)


def _identity(record):
    return {"id": record["id"], "name": record["name"], "link": record["link"]}


def _count(value):
    return len(value) if isinstance(value, list) else None


# ---- hotels/details ------------------------------------------------------------------------

def hotel_details(hotel):
    """Everything the hotel page and the static details API say about the
    property, except the provider rates (hotels/rates), the nearby hotels
    (hotels/nearby), the price charts (hotels/price-insights) and the
    review list (hotels/reviews) — those carry counts here."""
    r = _record(hotel)
    rates, nearby = r.get("rates") or {}, r.get("nearby_hotels") or {}
    return {
        **_identity(r),
        "has_page": r["has_page"],
        "alternate_names": r["alternate_names"],
        "classification": r["classification"],
        "stars": r["stars"],
        "description": r["description"],
        "description_source": r["description_source"],
        "about": r["about"],
        "licence_info": r["licence_info"],
        "official_website": r["official_website"],
        "phone": r["phone"],
        "check_in_time": r["check_in_time"],
        "check_out_time": r["check_out_time"],
        "address": r["address"],
        "coordinates": r["coordinates"],
        "distance_from_center": r["distance_from_center"],
        "city": r["city"],
        "currency": r["currency"],
        "price_range": r["price_range"],
        "latest_price": r["latest_price"],
        "rating": r["rating"],
        "reviews": r["reviews"],
        "policies": r["policies"],
        "policy_notes": r["policy_notes"],
        "highlights": r["highlights"],
        "good_to_know": r["good_to_know"],
        "amenities": r["amenities"],
        "freebies": r["freebies"],
        "cover_image": r["cover_image"],
        "photos": r["photos"],
        "photos_count": _count(r["photos"]),
        "photo_categories": r["photo_categories"],
        "nearby_places": r["nearby_places"],
        "nearby_landmarks": r["nearby_landmarks"],
        "nearby_transport": r["nearby_transport"],
        "static_map_link": r["static_map_link"],
        "faqs": r["faqs"],
        "ai_faqs": r["ai_faqs"],
        "tips": r["tips"],
        "ai_tips": r["ai_tips"],
        "review_sentiments": r["review_sentiments"],
        "rate_providers_count": _count(rates.get("providers")),
        "nearby_hotels_count": sum(len(v) for v in nearby.values() if isinstance(v, list)) if nearby else None,
        "meta": r["meta"],
    }


# ---- hotels/rates ----------------------------------------------------------------------------

def hotel_rates(hotel):
    """Room rows x provider offers from the hotel page, for the stay the site
    quotes on it (its default: a week out, 1 night, 2 adults, 1 room). A hotel
    without an SEO page has no rates here (null)."""
    r = _record(hotel)
    rates = r.get("rates") or {}
    return {
        **_identity(r),
        "stay": rates.get("stay"),
        "currency": rates.get("currency") or r["currency"],
        "cheapest": rates.get("cheapest"),
        "providers": rates.get("providers") or [],
        "providers_count": _count(rates.get("providers")) if rates else None,
    }


# ---- hotels/nearby ---------------------------------------------------------------------------

def hotel_nearby(hotel):
    """The hotel page's three nearby lists: closest, cheapest and most
    recommended hotels around this one (with price and rating)."""
    r = _record(hotel)
    nearby = r.get("nearby_hotels") or {}
    return {
        **_identity(r),
        "coordinates": r["coordinates"],
        "latest_price": r["latest_price"],
        "closest": nearby.get("closest") or [],
        "cheapest": nearby.get("cheapest") or [],
        "most_recommended": nearby.get("most_recommended") or [],
    }


# ---- hotels/price-insights --------------------------------------------------------------------

def _good_to_know(record, kind):
    for row in record.get("good_to_know") or []:
        if row.get("type") == kind:
            return row
    return None


def _season(row):
    if not row:
        return None
    return {"month": row.get("text"), "note": row.get("description")}


def _average(row, currency):
    if not row:
        return None
    amount = parsers.parse_number(row.get("text"))
    return {"amount": amount, "currency": currency if amount is not None else None,
            "text": row.get("text"), "note": row.get("description")}


def hotel_price_insights(hotel):
    """KAYAK's own price history for the property: cheapest time to book
    (price by days before the stay), average price by month and by day of
    week, low / high season, weeknight vs weekend averages, booking tips."""
    r = _record(hotel)
    charts = r.get("price_charts") or {}
    return {
        **_identity(r),
        "currency": r["currency"],
        "low_season": _season(_good_to_know(r, "lowSeason")),
        "high_season": _season(_good_to_know(r, "highSeason")),
        "average_weeknight_price": _average(_good_to_know(r, "workDaysPrice"), r["currency"]),
        "average_weekend_price": _average(_good_to_know(r, "weekendsPrice"), r["currency"]),
        "cheapest_time_to_book": charts.get("cheapest_time_to_book"),
        "monthly_prices": charts.get("monthly"),
        "weekly_prices": charts.get("weekly"),
        "tips": r["tips"],
    }


# ---- hotels/reviews ------------------------------------------------------------------------------

def _score_range(min_score, max_score):
    if min_score is None and max_score is None:
        return None
    lo = int(round((min_score or 0) * 10))
    hi = int(round((max_score if max_score is not None else 10) * 10))
    return (lo, hi)


def _hotel_reviews(hotel, page, sort, traveller_type, min_score, max_score, search, topic):
    start = (page - 1) * REVIEWS_PAGE_SIZE
    parsed = parsers.parse_reviews(fetch_reviews(
        hotel, start_index=start, sort=sort, traveller_types=traveller_type,
        score_range=_score_range(min_score, max_score), search=search, topic=topic))
    if parsed["total_count"] == 0 and page == 1 and not (traveller_type or min_score is not None
                                                          or max_score is not None or search or topic):
        # the review route answers an unknown id with an empty 200; the
        # static details route is a real 404 for it
        fetch_static_details(hotel)
    total = parsed["total_count"]
    return {
        "hotel_id": hotel,
        "filters": {"sort": sort, "traveller_type": traveller_type, "min_score": min_score,
                    "max_score": max_score, "search": search, "topic": topic},
        "results": parsed["reviews"],
        "pagination": {
            "page": page,
            "items_per_page": REVIEWS_PAGE_SIZE,
            "total_pages": math.ceil(total / REVIEWS_PAGE_SIZE) if total else 0,
            "total_count": total,
        },
    }


def hotel_reviews(**data):
    return cached_call("kayak.reviews", data, _hotel_reviews, ttl.REVIEWS_CACHE)


# ---- locations/search ------------------------------------------------------------------------------

def _locations_search(query, type):
    results = parsers.parse_locations(fetch_locations(query, type))
    if type == HOTELS_ONLY:
        results = [r for r in results if r["type"] == "hotel"]
    return {"query": query, "type": type, "count": len(results), "results": results}


def locations_search(**data):
    return cached_call("kayak.locations", data, _locations_search, ttl.LOCATIONS_CACHE)
