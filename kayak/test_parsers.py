"""Offline tests for the KAYAK parsers, reference resolvers and value
helpers.

    python -m pytest kayak/test_parsers.py -q

Fixtures are real www.kayak.com pages / JSON captured 2026-11-07
(kayak/fixtures/): the Miami International Airport Hotel page (rich), the
Basecamp Spitsbergen page (no cheapest-time-to-book chart), the site's 404
page, static details for the Miami hotel / an apartment without an SEO page
/ a guest house with zero reviews / an unknown id, review pages, review
scores, AI tags, score-by-source lists and smarty autocomplete lists. No
network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kayak import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        text = f.read()
    if name.endswith(".json"):
        return json.loads(text) if text.strip() else None
    if name.endswith(".txt"):
        return None if not text.strip() else text
    return text


@pytest.fixture(scope="module")
def miami():
    return P.parse_hotel_page(fixture("hotel_page_miami_airport.html"))


@pytest.fixture(scope="module")
def basecamp():
    return P.parse_hotel_page(fixture("hotel_page_basecamp_spitsbergen.html"))


@pytest.fixture(scope="module")
def miami_static():
    return P.parse_static_details(fixture("static_details_miami_airport.json"))


@pytest.fixture(scope="module")
def miami_record(miami, miami_static):
    return P.merge_hotel_record("61867", miami, miami_static)


@pytest.fixture(scope="module")
def sandavagur_record():
    return P.merge_hotel_record(
        "2355788", None, P.parse_static_details(fixture("static_details_sandavagur.json")),
        fixture("review_scores_sandavagur.json"), fixture("review_tags_empty.json"),
        fixture("score_by_source_sandavagur.json"))


# ---- refs -------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("61867", "61867"),
    (" 61867 ", "61867"),
    ("https://www.kayak.com/Miami-Hotels-Miami-International-Airport-Hotel.61867.ksp", "61867"),
    ("https://www.kayak.com/x.61867.ksp?foo=1", "61867"),
    ("https://www.kayak.co.uk/Miami-Hotels-Miami-International-Airport-Hotel.61867.ksp", "61867"),
    ("https://www.kayak.com/hotels/Miami-International-Airport-Hotel,Miami-p53912-h61867-details/2026-12-20/2026-12-22/2adults", "61867"),
    ("https://www.kayak.com/i/api/search/v1/static/hotels/details?hid=61867&reviewLimit=0", "61867"),
    ("//www.kayak.com/Hotel.2355788.ksp", "2355788"),
])
def test_resolve_hotel(value, expected):
    assert refs.resolve_hotel(value) == expected


@pytest.mark.parametrize("value", [
    "", "miami airport hotel", "61867a", "https://www.booking.com/hotel/us/x.html",
    "https://www.kayak.com/Miami-Hotels.14305.hotel.ksp/no-id", "https://www.kayak.com/stays",
])
def test_resolve_hotel_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_hotel(value)


def test_hotel_link():
    assert refs.hotel_link("61867") == "https://www.kayak.com/Hotel.61867.ksp"
    assert refs.hotel_link("61867", "Miami-Hotels-X") == "https://www.kayak.com/Miami-Hotels-X.61867.ksp"


# ---- helpers ---------------------------------------------------------------------------------

def test_value_helpers():
    assert P._month_year("Nov 2026") == "2026-11"
    assert P._month_year("Feb 2025") == "2025-02"
    assert P._month_year("sometime") == "sometime"
    assert P._month_year("") is None
    assert P._score10(66) == 6.6
    assert P._score10("96.0") == 9.6
    assert P._score10(None) is None
    assert P._num("6,228") == 6228
    assert P._num("$183") == 183
    assert P._num("3.0") == 3.0
    assert P._num("") is None
    assert P._text("<p>Hi <b>there</b> &amp; you</p>") == "Hi there & you"
    assert P._cdn_link("/rimg/himg/a.jpg") == "https://content.r9cdn.net/rimg/himg/a.jpg"
    assert P._cdn_link("/provider-logos/hotels/h/x.png") == "https://content.r9cdn.net/rimg/provider-logos/hotels/h/x.png"
    assert P._cdn_link("https://content.r9cdn.net/x.png") == "https://content.r9cdn.net/x.png"
    assert P._site_link("/Miami-Hotels.14305.hotel.ksp") == "https://www.kayak.com/Miami-Hotels.14305.hotel.ksp"
    assert P._unwrap_out("https://www.kayak.com/out?url=https%3A%2F%2Fwww.agoda.com%2Fx%3Fa%3D1&trackClickOut=true") == \
        "https://www.agoda.com/x?a=1"
    assert P._unwrap_out("https://www.agoda.com/x") == "https://www.agoda.com/x"
    assert P._id(61867) == "61867" and P._id("61867") == "61867" and P._id(None) is None


# ---- the hotel page ---------------------------------------------------------------------------

def test_not_found_page_parses_to_none():
    assert P.parse_hotel_page(fixture("hotel_page_not_found.html")) is None
    assert P.parse_hotel_page("") is None
    assert P.parse_hotel_page("<html><title>x</title></html>") is None


def test_page_identity(miami):
    assert miami["id"] == "61867"
    assert miami["name"] == "Miami International Airport Hotel"
    assert miami["link"] == "https://www.kayak.com/Miami-Hotels-Miami-International-Airport-Hotel.61867.ksp"
    assert miami["slug"] == "Miami-Hotels-Miami-International-Airport-Hotel"
    assert miami["stars"] == 3
    assert miami["classification_code"] == "hotel"
    assert miami["phone"] == "+1 305 871 4100"
    assert miami["address"]["postal_code"] == "33122"
    assert miami["address"]["region"] == "Florida"
    assert miami["address"]["country_code"] == "US"
    assert miami["coordinates"] == {"lat": 25.794996, "lng": -80.27852}
    assert miami["city"] == {"id": "14305", "name": "Miami", "link": "https://www.kayak.com/Miami-Hotels.14305.hotel.ksp"}
    assert miami["rating"] == {"score": 6.6, "best_score": 10, "review_count": 7927}
    assert miami["currency"] == "USD"
    assert miami["latest_price"] == {"amount": 180.2, "currency": "USD"}
    assert miami["about"].startswith("For the ultimate convenience")
    assert "<p>" not in miami["about"]
    assert miami["meta"]["title"].startswith("Miami International Airport Hotel")
    assert miami["meta"]["rendered_at"].startswith("2026-11-07")


def test_page_content_sections(miami):
    assert miami["amenities"]["count"] == 57
    assert "Restaurant" in miami["amenities"]["top"]
    assert miami["amenities"]["categories"][0]["name"] == "Services and conveniences"
    assert {"code": "atm", "name": "ATM on-site"} in miami["amenities"]["categories"][0]["amenities"]
    assert len(miami["photos"]) == 34
    photo = miami["photos"][0]
    assert photo["link"].startswith("https://content.r9cdn.net/rimg/himg/") and photo["category"] == "Bedroom"
    assert photo["alt_text"] and photo["id"] == "2651197754"
    assert "Bedroom" in miami["photo_categories"]
    assert len(miami["nearby_places"]) == 12 and miami["nearby_places"][0]["name"] == "Norwegian Cruise Line"
    assert miami["nearby_places"][0]["coordinates"]["lat"] == 25.791801
    assert len(miami["faqs"]) == 10 and miami["faqs"][0]["question"].startswith("What are the best rooms")
    assert len(miami["ai_faqs"]) == 5 and miami["ai_faqs"][0]["answer"]
    assert len(miami["tips"]) == 4 and len(miami["ai_tips"]) == 10
    assert miami["ai_tips"][0] == {"title": "Opt for a Room on a Higher Floor",
                                   "text": miami["ai_tips"][0]["text"]}
    assert [p["type"] for p in miami["policies"]] == ["other", "hotelCancellation"]
    good = {g["type"]: g for g in miami["good_to_know"]}
    assert good["lowSeason"]["text"] == "August"
    assert good["workDaysPrice"]["text"] == "$183"
    assert good["lowSeason"]["description"] == "Cheapest month to stay with an average 14% drop in price."
    assert len(miami["review_sentiments"]) == 16


def test_page_review_summary(miami):
    rv = miami["reviews"]
    assert rv["score"] == 6.6 and rv["review_count"] == 7927
    assert rv["review_count_by_traveller_type"] == {"friends": 184, "couples": 1128, "solo": 1103, "families": 593}
    assert rv["score_by_traveller_type"] is None
    assert rv["pros"][0]["text"] == "Location was in the airport-perfect" and rv["pros"][0]["count"] == 236
    assert len(rv["pros"][0]["examples"]) == 5
    assert rv["tags"][0] == {"tag": "great location", "count": 897}
    assert rv["ai_tags"][0] == {"name": "Location", "code": "location", "sentiment": "positive", "score": 10, "review_count": 18}
    assert rv["ai_summary"].startswith("Guests overwhelmingly appreciate")
    assert rv["score_distribution"][0] == {"min_score": 0.0, "max_score": 4.0, "review_count": 843}
    assert rv["score_distribution"][-1] == {"min_score": 9.0, "max_score": 10.0, "review_count": 1470}
    assert rv["by_source"][0]["source"]["name"] == "Booking.com"
    assert rv["by_source"][0]["review_count"] == 2651 and rv["by_source"][0]["average_score"] == 7.3
    assert rv["by_source"][0]["source"]["logo"].startswith("https://content.r9cdn.net/rimg/provider-logos/")


def test_page_rates(miami):
    rates = miami["rates"]
    assert rates["stay"] == {"check_in": "2026-11-14", "check_out": "2026-11-15", "nights": 1, "adults": 2, "rooms": 1}
    assert rates["currency"] == "USD"
    assert len(rates["providers"]) == 19
    first = rates["providers"][0]
    assert first["provider"] == {"code": "KAYAK", "name": "KAYAK", "logo": first["provider"]["logo"]}
    assert first["provider"]["logo"].startswith("https://content.r9cdn.net/rimg/provider-logos/")
    assert first["has_other_deals"] is False
    room = first["rooms"][0]
    assert room["description"] == "Standard room"
    option = room["options"][0]
    assert option["price"] == {"amount": 132.56, "currency": "USD", "text": "$133"}
    assert option["total_price"]["amount"] == 132.56
    assert option["rate_type"] == "bestAvailable" and option["beds"] == {"queen": 1}
    assert option["booking_link"] is None          # "" -> null
    assert option["is_private_deal"] is False and option["freebies"] == []
    assert rates["cheapest"]["amount"] <= 132.56 and rates["cheapest"]["currency"] == "USD"
    assert rates["cheapest"]["provider"] and rates["cheapest"]["room"]
    # noBedType rows: 0 -> null, n -> {"unspecified": n}
    beds = [o["beds"] for p in rates["providers"] for r in p["rooms"] for o in r["options"]]
    assert None in beds and {"unspecified": 2} in beds


def test_page_nearby_and_charts(miami):
    nb = miami["nearby_hotels"]
    assert len(nb["closest"]) == 4 and len(nb["cheapest"]) == 4 and len(nb["most_recommended"]) == 4
    hilton = nb["closest"][0]
    assert hilton["id"] == "31896" and hilton["name"] == "Hilton Miami Airport Blue Lagoon"
    assert hilton["link"] == "https://www.kayak.com/Miami-Hotels-Hilton-Miami-Airport-Blue-Lagoon.31896.ksp"
    assert hilton["rating"] == {"score": 7.5, "text": "Good", "review_count": 6228}
    assert hilton["distance"] == {"miles": 0.8985728462398858, "text": "0.9 mi"}
    assert hilton["price"] == {"amount": 149.32, "currency": "USD", "text": "$150+"}
    assert hilton["top_amenities"] == ["Outdoor pool", "Fitness center", "Restaurant"]
    assert hilton["classification"] == "4-star hotel" and hilton["is_hotel"] is True
    rental = nb["most_recommended"][0]
    assert rental["link"] == "https://www.kayak.com/Hotel.1070375515.ksp"    # no url on the page -> id link
    charts = miami["price_charts"]
    assert len(charts["cheapest_time_to_book"]["points"]) == 90
    assert charts["cheapest_time_to_book"]["points"][0] == {"label": "90", "price": 161}
    assert charts["cheapest_time_to_book"]["advice"].startswith("To get the best price")
    assert [p["label"] for p in charts["monthly"]["points"]][:3] == ["Jan", "Feb", "Mar"]
    assert charts["weekly"]["points"][1] == {"label": "Tue", "price": 180}


def test_sparse_page(basecamp):
    assert basecamp["id"] == "384331" and basecamp["name"] == "Basecamp Spitsbergen Hotel"
    assert basecamp["price_charts"]["cheapest_time_to_book"] is None
    assert basecamp["price_charts"]["monthly"] and basecamp["price_charts"]["weekly"]
    assert len(basecamp["rates"]["providers"]) == 3
    assert len(basecamp["reviews"]["by_source"]) == 1
    assert basecamp["rating"]["score"] == 9.5
    assert basecamp["address"]["country"] == "Norway"


# ---- static details ----------------------------------------------------------------------------

def test_static_details(miami_static):
    s = miami_static
    assert s["id"] == "61867" and s["name"] == "Miami International Airport Hotel"
    assert s["classification"] == {"code": "hotel", "name": "Hotel"}
    assert s["stars"] == 3.0
    assert s["check_in_time"] == "15:00:00" and s["check_out_time"] == "12:00:00"
    assert s["currency"] == "USD" and s["country_code"] == "US" and s["city"] == "Miami"
    assert s["description"].startswith("This smoke-free hotel") and s["description_source"] == "Expedia Group"
    assert s["property_description"] is None
    assert [p["code"] for p in s["policies"]] == ["cancellation", "checkin", "checkout"]
    assert s["highlights"][0]["title"] == "Hotel Room"
    assert s["coordinates"] == {"lat": 25.794996, "lng": -80.27852}
    assert s["distance_from_center"] == {"value": 5.55, "unit": "mi", "text": "5.5 mi"}
    assert len(s["nearby_transport"]) == 44
    assert s["nearby_transport"][0]["type"] == "airport" and s["nearby_transport"][0]["duration_minutes"] == 7
    assert s["nearby_transport"][0]["distance"]["text"] == "7 min walk"
    assert s["amenities"]["count"] == 57 or s["amenities"]["categories"]
    assert s["freebies"] == [{"code": "wififree", "name": "Free Wi-Fi", "category": "Internet"}]
    assert len(s["photos"]) == 51 and s["photos"][0]["link"].startswith("https://content.r9cdn.net/rimg/himg/")
    assert s["static_map_link"].startswith("http://maps.googleapis.com/")


def test_static_details_sparse_and_missing():
    s = P.parse_static_details(fixture("static_details_sandavagur.json"))
    assert s["id"] == "2355788" and s["classification"]["code"] == "apartment"
    assert s["stars"] is None and s["phone"] is None and s["description"] is None
    assert s["currency"] == "DKK" and s["country_code"] == "FO"
    assert s["amenities"] == {"count": None, "top": [], "categories": []}
    assert len(s["nearby_transport"]) == 1
    assert P.parse_static_details(fixture("static_details_not_found.json")) is None
    assert P.parse_static_details(None) is None
    assert P.parse_static_details({}) is None


# ---- merged record -----------------------------------------------------------------------------

def test_merged_record_prefers_page_then_static(miami_record):
    r = miami_record
    assert r["has_page"] is True
    assert r["link"].endswith(".61867.ksp") and r["slug" if "slug" in r else "id"]
    assert r["check_in_time"] == "15:00:00"            # static only
    assert r["address"]["postal_code"] == "33122"      # page only
    assert r["description_source"] == "Expedia Group"
    assert r["classification"] == {"code": "hotel", "name": "Hotel"}
    assert len(r["nearby_transport"]) == 44 and len(r["photos"]) == 34
    assert len(r["policy_notes"]) == 3 and len(r["highlights"]) == 2
    assert r["reviews"]["by_source"] and r["rates"] and r["nearby_hotels"]


def test_merged_record_without_page(sandavagur_record):
    r = sandavagur_record
    assert r["has_page"] is False
    assert r["id"] == "2355788" and r["name"] == "Bed & Breakfast Sandavagur"
    assert r["link"] == "https://www.kayak.com/Hotel.2355788.ksp"
    assert r["rates"] is None and r["nearby_hotels"] is None
    assert r["price_charts"] == {"cheapest_time_to_book": None, "monthly": None, "weekly": None}
    assert r["rating"] == {"score": 9.2, "best_score": 10, "review_count": 237}
    rv = r["reviews"]
    assert rv["score"] == 9.2 and rv["review_count"] == 237
    assert rv["score_by_traveller_type"] == {"couples": 9.2, "friends": 8.8, "solo": 9.3, "families": 9.2}
    assert rv["ai_tags"] == [] and rv["ai_summary"] is None
    assert rv["score_distribution"] is None
    assert rv["by_source"][0]["source"]["id"] == "BOOKING" and rv["by_source"][0]["average_score"] == 9.2
    assert r["address"] == {"full": None, "street": None, "city": "Sandavágur", "region": None,
                            "postal_code": None, "country": None, "country_code": "FO"}
    assert r["photos"] == [] and r["cover_image"] is None


def test_merged_record_zero_reviews():
    r = P.merge_hotel_record("1073017391", None, P.parse_static_details(fixture("static_details_guesthouse_no_reviews.json")),
                             fixture("review_scores_empty.txt"), fixture("review_tags_empty.json"), None)
    assert r["reviews"] is None and r["rating"] is None
    assert r["classification"] == {"code": "guestHouse", "name": "Guest house"}
    assert len(r["photos"]) == 17 and r["cover_image"] == r["photos"][0]["link"]


# ---- reviews -------------------------------------------------------------------------------------

def test_reviews_page():
    page = P.parse_reviews(fixture("reviews_miami_airport_p1.json"))
    assert page["total_count"] == 3270 and len(page["reviews"]) == 10
    first = page["reviews"][0]
    assert first["id"] == "zLrwr6EBZkMaSQmeAIB-" and first["date"] == "2026-11"
    assert first["score"] == 9.6 and first["rating_text"] == "Excellent"
    assert first["comment"].startswith("The hotel is situated in the airport")
    assert first["author"] == "Anonymous" and first["is_kayak_review"] is False
    assert first["source"]["name"] == "Agoda.com"
    assert first["source"]["link"].startswith("https://www.agoda.com/")       # unwrapped from /out?url=
    assert first["source"]["logo"] == "https://content.r9cdn.net/rimg/provider-logos/hotels/reviews/h/agodaLogo.png"
    split = next(r for r in page["reviews"] if r["positive"])
    assert split["comment"] is None and split["negative"]
    page2 = P.parse_reviews(fixture("reviews_miami_airport_p2.json"))
    assert page2["total_count"] == 3270 and page2["reviews"][0]["date"] == "2026-10"


def test_reviews_sorted_and_empty():
    asc = P.parse_reviews(fixture("reviews_sandavagur_score_asc.json"))
    scores = [r["score"] for r in asc["reviews"]]
    assert asc["total_count"] == 88 and scores == sorted(scores)
    assert P.parse_reviews(fixture("reviews_empty.json")) == {"total_count": 0, "reviews": []}
    assert P.parse_reviews(None) == {"total_count": 0, "reviews": []}


def test_review_tags_and_sources():
    tags, summary = P.parse_review_tags(fixture("review_tags_miami_airport.json"))
    assert len(tags) == 4 and tags[0]["name"] == "location"
    assert summary.startswith("Guests overwhelmingly appreciate")
    assert P.parse_review_tags(fixture("review_tags_empty.json")) == ([], None)
    assert P.parse_review_tags(None) == ([], None)
    sources = P._by_source(P.parse_score_by_source(fixture("score_by_source_miami_airport.json")))
    assert len(sources) == 5 and sources[0]["source"]["name"] == "Booking.com"
    assert "KAYAK" in [s["source"]["name"] for s in sources]
    assert sources[0]["total_count"] == 7100
    assert P.parse_score_by_source(None) == []


def test_review_summary_from_scores_api():
    summary = P.review_summary(fixture("review_scores_miami_airport.json"),
                               ai_tags=P.parse_review_tags(fixture("review_tags_miami_airport.json"))[0],
                               by_source=P.parse_score_by_source(fixture("score_by_source_miami_airport.json")))
    assert summary["score"] == 6.6 and summary["review_count"] == 7927
    assert len(summary["ai_tags"]) == 4 and summary["score_distribution"] is None
    assert len(summary["by_source"]) == 5
    assert P.review_summary(None) is None
    assert P.review_summary({}) is None


# ---- autocomplete --------------------------------------------------------------------------------

def test_locations_stays():
    rows = P.parse_locations(fixture("locations_stays_las_vegas.json"))
    assert len(rows) == 6
    vegas = rows[0]
    assert vegas["id"] == "35107" and vegas["name"] == "Las Vegas, Nevada, United States" and vegas["type"] == "city"
    assert vegas["short_name"] == "Las Vegas"
    assert vegas["place_id"] == "61746" and vegas["airport_code"] == "LAS"
    assert vegas["city"]["id"] == "35107"
    assert vegas["region"] == {"id": "146", "code": "NV", "name": "Nevada"}
    assert vegas["country"]["code"] == "US"
    assert vegas["timezone"] == "America/Los_Angeles"
    assert vegas["bounding_box"]["west"] == -115.414628
    assert vegas["hotel_id"] is None and vegas["link"] is None
    assert [r["type"] for r in rows] == ["city", "airport", "city", "airport", "city", "hotel"]
    las = rows[1]
    assert las["airport_code"] == "LAS" and las["city"]["id"] == "35107"
    beverly = P.parse_locations(fixture("locations_stays_beverly_hills.json"))
    assert beverly[0]["name"] == "Beverly Hills, California, United States" and beverly[0]["type"] == "city"
    bh_hotel = beverly[-1]
    assert bh_hotel["type"] == "hotel" and bh_hotel["hotel_id"] == "10760"
    assert bh_hotel["link"] == "https://www.kayak.com/Hotel.10760.ksp"


def test_locations_loctypes_are_readable():
    hotels = P.parse_locations(fixture("locations_hotels_bellagio.json"))
    assert [r["type"] for r in hotels] == ["city", "hotel", "hotel", "hotel", "landmark", "hotel"]
    nearby_airports = P.parse_locations(fixture("locations_flights_beverly_hills.json"))
    assert {r["type"] for r in nearby_airports} == {"airport"}          # loctype "apnc"
    assert nearby_airports[0]["airport_code"] == "TPA" and nearby_airports[0]["name"] == "Tampa"
    assert P.parse_location({"id": "1", "displayname": "x", "loctype": "hood"})["type"] == "neighborhood"
    assert P.parse_location({"id": "1", "displayname": "x", "loctype": "ctry"})["type"] == "country"
    assert P.parse_location({"id": "1", "displayname": "x", "loctype": "reg"})["type"] == "region"
    assert P.parse_location({"id": "1", "displayname": "x", "loctype": "freereg"})["type"] == "region"
    assert P.parse_location({"id": "1", "displayname": "x", "loctype": "newkind"})["type"] == "newkind"


def test_locations_hotels_type_keeps_only_hotels(monkeypatch):
    from kayak import api
    monkeypatch.setattr(api, "fetch_locations", lambda query, kind: fixture("locations_hotels_bellagio.json"))
    out = api._locations_search("bellagio", "hotels")
    assert out["count"] == 4 and {r["type"] for r in out["results"]} == {"hotel"}
    assert "64677" in [r["hotel_id"] for r in out["results"]]
    out = api._locations_search("bellagio", "stays")
    assert out["count"] == 6


def test_locations_other_types():
    flights = P.parse_locations(fixture("locations_flights_london.json"))
    assert flights[0]["type"] == "airport" and flights[0]["airport_code"] == "LON" and flights[0]["is_metro_only"] is True
    assert flights[0]["airport_name"] == "All airports"
    cars = P.parse_locations(fixture("locations_cars_los_angeles.json"))
    assert [r["type"] for r in cars][:2] == ["airport", "city"]
    assert cars[0]["airport_code"] == "LAX" and cars[1]["id"] == "16078" and cars[1]["city"]["id"] == "16078"
    hotels = P.parse_locations(fixture("locations_hotels_hilton_miami.json"))
    assert len(hotels) == 6 and all(h["type"] == "hotel" for h in hotels)
    assert hotels[0]["hotel_id"] == "31896" and hotels[0]["link"] == "https://www.kayak.com/Hotel.31896.ksp"
    assert hotels[0]["short_name"] == "Hilton Miami Airport Blue Lagoon"
    assert hotels[0]["bounding_box"] is None and hotels[0]["image"] is None
    assert P.parse_locations(fixture("locations_empty.json")) == []
    assert P.parse_locations(None) == []
    assert P.parse_locations([{"junk": 1}, "x"]) == []


# ---- robustness ------------------------------------------------------------------------------------

def test_partial_inputs_never_crash():
    assert P.parse_hotel_page('<html><script id="jsonData_R9DataStorage" type="application/json">{"serverData":{}}</script></html>') is None
    rec = P.merge_hotel_record("1", None, {"id": "1", "name": "x"}, None, None, None)
    assert rec["name"] == "x" and rec["reviews"] is None and rec["amenities"] is None
    assert P.parse_review({}) ["id"] is None
    assert P._nearby_hotel({})["link"] is None
    assert P._rates({}) is None
    assert P._chart({}) is None
    assert P.parse_location({"id": 5}) ["id"] == "5"
