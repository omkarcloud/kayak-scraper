"""Offline tests for the /kayak/* request schemas.

    python -m pytest kayak/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kayak import schemas  # noqa: E402

LINK = "https://www.kayak.com/Miami-Hotels-Miami-International-Airport-Hotel.61867.ksp"


def test_hotel_schema_accepts_id_and_links():
    assert schemas.HotelSchema().load({"hotel": "61867"}) == {"hotel": "61867"}
    assert schemas.HotelSchema().load({"hotel": LINK}) == {"hotel": "61867"}
    assert schemas.HotelSchema().load({"hotel": "https://www.kayak.com/x.61867.ksp"}) == {"hotel": "61867"}
    assert schemas.HotelSchema().load(
        {"hotel": "https://www.kayak.com/hotels/X,Miami-p53912-h61867-details/2026-12-20/2026-12-22/2adults"}
    ) == {"hotel": "61867"}


@pytest.mark.parametrize("value", ["", "miami airport hotel", "https://www.booking.com/hotel/x.html",
                                   "https://www.kayak.com/stays"])
def test_hotel_schema_rejects(value):
    with pytest.raises(ValidationError) as e:
        schemas.HotelSchema().load({"hotel": value})
    assert "hotel" in e.value.messages


def test_hotel_schema_requires_hotel_and_rejects_siblings():
    with pytest.raises(ValidationError):
        schemas.HotelSchema().load({})
    with pytest.raises(ValidationError):
        schemas.HotelSchema().load({"hotel": "61867", "id": "61867"})
    with pytest.raises(ValidationError):
        schemas.HotelSchema().load({"hotel": "61867", "url": LINK})


def test_reviews_schema_defaults_and_mapping():
    loaded = schemas.HotelReviewsSchema().load({"hotel": LINK})
    assert loaded == {"hotel": "61867", "page": 1, "sort": "recent", "traveller_type": None,
                      "min_score": None, "max_score": None, "search": None, "topic": None}
    loaded = schemas.HotelReviewsSchema().load({
        "hotel": "61867", "page": "3", "sort": "Highest", "traveller_type": "Families, solo,families",
        "min_score": "8", "max_score": "10", "search": " airport ", "topic": "great location"})
    assert loaded["page"] == 3 and loaded["sort"] == "scoreDesc"
    assert loaded["traveller_type"] == ["families", "solo"]
    assert loaded["min_score"] == 8.0 and loaded["max_score"] == 10.0
    assert loaded["search"] == "airport" and loaded["topic"] == "great location"
    assert schemas.HotelReviewsSchema().load({"hotel": "61867", "sort": "lowest"})["sort"] == "scoreAsc"
    assert schemas.HotelReviewsSchema().load({"hotel": "61867", "sort": "oldest"})["sort"] == "oldest"


@pytest.mark.parametrize("params,field", [
    ({"hotel": "61867", "sort": "best"}, "sort"),
    ({"hotel": "61867", "traveller_type": "business"}, "traveller_type"),
    ({"hotel": "61867", "min_score": "11"}, "min_score"),
    ({"hotel": "61867", "max_score": "-1"}, "max_score"),
    ({"hotel": "61867", "min_score": "9", "max_score": "5"}, "min_score"),
    ({"hotel": "61867", "page": "0"}, "page"),
    ({"hotel": "61867", "page": str(schemas.MAX_REVIEW_PAGE + 1)}, "page"),
    ({"hotel": "61867", "search": "x" * 101}, "search"),
    ({"hotel": "61867", "limit": "10"}, "limit"),
])
def test_reviews_schema_rejects(params, field):
    with pytest.raises(ValidationError) as e:
        schemas.HotelReviewsSchema().load(params)
    assert field in e.value.messages, e.value.messages


def test_locations_schema():
    loaded = schemas.LocationsSearchSchema().load({"query": " Paris "})
    assert loaded == {"query": "Paris", "type": "stays"}
    for kind in ("stays", "hotels", "flights", "cars", "Flights"):
        assert schemas.LocationsSearchSchema().load({"query": "x", "type": kind})["type"] == kind.lower()
    with pytest.raises(ValidationError) as e:
        schemas.LocationsSearchSchema().load({"query": "x", "type": "trains"})
    assert "type" in e.value.messages
    with pytest.raises(ValidationError):
        schemas.LocationsSearchSchema().load({})
    with pytest.raises(ValidationError):
        schemas.LocationsSearchSchema().load({"query": ""})
    with pytest.raises(ValidationError):
        schemas.LocationsSearchSchema().load({"query": "x" * 101})
    with pytest.raises(ValidationError):
        schemas.LocationsSearchSchema().load({"query": "x", "vertical": "hotels"})


def test_error_messages_name_the_accepted_forms():
    with pytest.raises(ValidationError) as e:
        schemas.HotelSchema().load({"hotel": "nope"})
    assert "kayak.com hotel link" in e.value.messages["hotel"][0]
    with pytest.raises(ValidationError) as e:
        schemas.HotelReviewsSchema().load({"hotel": "61867", "sort": "zzz"})
    assert "recent, oldest, highest, lowest" in e.value.messages["sort"][0]
