"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Params go through the same schemas the API uses, so a
kayak.com hotel link works anywhere a hotel ID does and defaults are filled in.
"""
import json
import os

from kayak.api import hotel_details, hotel_reviews, locations_search
from kayak.schemas import HotelReviewsSchema, HotelSchema, LocationsSearchSchema

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a hotel ID or any kayak.com hotel link resolves to the same hotel
    bellagio = HotelSchema().load({"hotel": "https://www.kayak.com/Las-Vegas-Hotels-Bellagio.64677.ksp"})
    save("hotel_bellagio.json", hotel_details(**bellagio))

    # 10 guest reviews per page, newest first
    save("reviews_bellagio.json", hotel_reviews(**HotelReviewsSchema().load({"hotel": "64677", "sort": "recent"})))

    # cities, airports, landmarks and hotels with the IDs KAYAK uses
    save("locations_las_vegas.json", locations_search(**LocationsSearchSchema().load({"query": "Las Vegas"})))
