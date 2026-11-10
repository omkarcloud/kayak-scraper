"""Marshmallow request schemas for every /kayak/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    hotel      a KAYAK hotel id (61867) OR any kayak.com hotel link (the SEO
               page /<City>-Hotels-<Name>.<id>.ksp, a slug-less /x.<id>.ksp,
               a results-page -h<id>- detail link, or ...?hid=<id>)
    query      autocomplete text
    type       locations/search result mix (kayak/refs.py LOCATION_TYPES)

Review filters are the ones the site's own review widget sends and the
endpoint honours (kayak/refs.py): sort, traveller_type, min_score /
max_score (the displayed 0-10 scale), search, topic.
"""
from marshmallow import ValidationError, validate, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, NonNegativeNumber, PageField,
                           QueryField, RefField, StrippedString)
from kayak import refs

# 10 reviews per call is the site's hard cap; 3,270 reviews = 327 pages.
# Deeper requests answer an empty page (the site returns none past the end).
MAX_REVIEW_PAGE = 1000


class HotelRefField(RefField):
    resolver = staticmethod(refs.resolve_hotel)


class ScoreField(NonNegativeNumber):
    """A review score on the displayed 0-10 scale."""

    def __init__(self, **kwargs):
        kwargs.setdefault("validate", validate.Range(min=0, max=10))
        super().__init__(**kwargs)


class HotelSchema(BaseSchema):
    hotel = HotelRefField(metadata={"description": "KAYAK hotel id (61867), or a kayak.com hotel link"})


class HotelReviewsSchema(BaseSchema):
    hotel = HotelRefField(metadata={"description": "KAYAK hotel id (61867), or a kayak.com hotel link"})
    page = PageField(max_page=MAX_REVIEW_PAGE, metadata={"description": "1-based page, 10 reviews per page"})
    sort = ChoiceField(refs.REVIEW_SORTS, load_default="recent", metadata={
        "description": "recent (default), oldest, highest (score) or lowest (score)"})
    traveller_type = CommaListField(allowed=list(refs.TRAVELLER_TYPES), upper=False, max_items=4, metadata={
        "description": "comma list of families, couples, solo, friends"})
    min_score = ScoreField(metadata={"description": "lowest review score to include, 0-10"})
    max_score = ScoreField(metadata={"description": "highest review score to include, 0-10"})
    search = StrippedString(required=False, load_default=None, validate=validate.Length(max=100), metadata={
        "description": "free text the review must mention"})
    topic = StrippedString(required=False, load_default=None, validate=validate.Length(max=60), metadata={
        "description": "one of the hotel's review tags from hotels/details (e.g. 'great location')"})

    @validates_schema
    def _score_order(self, data, **kwargs):
        lo, hi = data.get("min_score"), data.get("max_score")
        if lo is not None and hi is not None and lo > hi:
            raise ValidationError("min_score must not exceed max_score.", "min_score")


class LocationsSearchSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={"description": "place, airport or hotel name to look up"})
    type = ChoiceField(list(refs.LOCATION_TYPES), load_default="stays", metadata={
        "description": "stays (cities, neighborhoods, landmarks, regions, airports and hotels for a hotel "
                       "search, default), hotels (hotel properties only, with their hotel id), flights "
                       "(airports and metro areas), cars (airports and cities for a car-rental pick-up)"})
