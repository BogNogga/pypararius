"""Parser utilities for Pararius responses - extracts structured JSON-LD data.

The detail pages expose most data in two places:

1. JSON-LD (``application/ld+json``) — reliable, machine-readable: price, area,
   rooms, bedrooms, bathrooms, coordinates, year built, date posted, pets.
2. HTML ``<dl class="listing-features__list">`` feature tables — energy label,
   deposit, interior, availability, facilities, etc. (not present in JSON-LD).

Pararius renders the feature table with a stray space before the closing ``>``
of several tags (``<span ..." >``) and breaks some ``<span>`` tags across lines,
which defeats naive regexes. ``_extract_features`` below is deliberately robust
to all of these variations and parses each ``<dt>/<dd>`` pair as a whole.
"""

import html as html_lib
import json
import re
from typing import Optional

from .listing import Listing


# ---------------------------------------------------------------------------
# Search results
# ---------------------------------------------------------------------------

def parse_search_response(response_text: str, city: str) -> list[Listing]:
    """Parse search results from either Pararius AJAX JSON or full HTML."""
    html = response_text

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        components = data.get("components", {})
        if isinstance(components, dict):
            results = components.get("results")
            if isinstance(results, str):
                html = results

    listings = parse_search_jsonld(html, city)

    # Enrich with per-listing visibility badges and the search total count.
    total_count = _extract_total_count(html)
    badges = _extract_badges(html)
    for listing in listings:
        label = badges.get(listing.listing_id) if listing.listing_id else None
        listing.data["label"] = label
        listing.data["featured"] = label == "Highlighted"
        listing.data["is_new"] = label == "New"
        listing.data["total_count"] = total_count

    return listings


def _extract_total_count(html: str) -> Optional[int]:
    """Extract the total number of active listings from the search header."""
    match = re.search(r'search-list-header__count">([\d.,]+)</span>', html)
    if not match:
        return None
    digits = match.group(1).replace(".", "").replace(",", "")
    return int(digits) if digits.isdigit() else None


def _extract_badges(html: str) -> dict[str, str]:
    """Map listing ID -> visibility badge ('Highlighted' or 'New').

    The badge lives in the listing-card HTML (``listing-label--featured`` /
    ``listing-label--new``), not in the JSON-LD ItemList, so it is parsed
    directly from the rendered search cards.
    """
    badges = {}
    label_map = {"featured": "Highlighted", "new": "New"}
    cards = re.split(r'<section\s+class="listing-search-item', html)[1:]
    for card in cards:
        url_match = re.search(r'href="(/[a-z-]+-for-(?:rent|sale)/[^"]+)"', card)
        if not url_match:
            continue
        parts = url_match.group(1).rstrip("/").split("/")
        if len(parts) < 2:
            continue
        listing_id = parts[-2]
        label_match = re.search(r'listing-label listing-label--(\w+)', card)
        label = label_map.get(label_match.group(1)) if label_match else None
        badges[listing_id] = label
    return badges


def parse_search_jsonld(html: str, city: str) -> list[Listing]:
    """Parse search results from JSON-LD structured data embedded in the page."""
    jsonld = _extract_jsonld_graph(html)

    for node in jsonld:
        types = node.get("@type", [])
        if isinstance(types, str):
            types = [types]
        main_entity = node.get("mainEntity", {})
        if main_entity.get("@type") == "ItemList":
            return _parse_itemlist(main_entity, city)

    return []


def _parse_itemlist(itemlist: dict, city: str) -> list[Listing]:
    """Parse an ItemList from JSON-LD into Listing objects."""
    listings = []
    for entry in itemlist.get("itemListElement", []):
        item = entry.get("item", {})
        if not item:
            continue

        url = item.get("url", "")
        listing_id = ""
        if url:
            parts = url.rstrip("/").split("/")
            if len(parts) >= 2:
                listing_id = parts[-2]

        price = None
        currency = "EUR"
        offers = item.get("offers", {})
        if offers:
            price_val = offers.get("price")
            if price_val is not None:
                price = int(float(price_val))
            currency = offers.get("priceCurrency", "EUR")

        price_formatted = f"\u20ac{price:,} per month" if price else None

        geo = item.get("geo", {})
        latitude = geo.get("latitude")
        longitude = geo.get("longitude")

        image = item.get("image")

        listing_data = {
            "title": item.get("name", ""),
            "city": city.title(),
            "price": price,
            "price_formatted": price_formatted,
            "currency": currency,
            "url": url,
            "photos": [image] if image else [],
            "photo_urls": [image] if image else [],
        }

        if latitude is not None and longitude is not None:
            listing_data["latitude"] = latitude
            listing_data["longitude"] = longitude
            listing_data["coordinates"] = (latitude, longitude)

        listings.append(Listing(listing_id=listing_id, data=listing_data))

    return listings


# ---------------------------------------------------------------------------
# Listing details
# ---------------------------------------------------------------------------

def parse_listing_details(html: str, url: str) -> Listing:
    """Parse full listing details from detail page JSON-LD + HTML features."""
    listing_id = url.rstrip("/").split("/")[-2] if "/" in url else ""

    jsonld = _extract_jsonld_detail(html)

    # --- Basic info from JSON-LD ---
    name = jsonld.get("name", "")
    description = jsonld.get("description")
    main_image = jsonld.get("image")

    # Address (note: Pararius puts the *neighbourhood* in ``addressRegion``)
    addr_data = jsonld.get("address", {}) or {}
    street = addr_data.get("streetAddress", "")
    city = addr_data.get("addressLocality", "")
    postcode = addr_data.get("postalCode")
    neighbourhood = addr_data.get("addressRegion")

    # Rooms / area / price
    rooms = None
    rooms_data = jsonld.get("numberOfRooms", [])
    if isinstance(rooms_data, list) and rooms_data:
        rooms = rooms_data[0].get("value")

    living_area = None
    floor_data = jsonld.get("floorSize", {})
    if floor_data:
        living_area = floor_data.get("value")

    price = None
    currency = "EUR"
    offer = jsonld.get("offers", {}) or {}
    if offer:
        price_str = offer.get("price")
        if price_str is not None:
            price = int(float(price_str))
        currency = offer.get("priceCurrency", "EUR")

    # --- Extra structured fields straight from JSON-LD ---
    bedrooms = _as_int(jsonld.get("numberOfBedrooms"))
    bathrooms = _as_int(jsonld.get("numberOfBathroomsTotal"))
    year_built = _as_int(jsonld.get("yearBuilt"))
    date_posted = jsonld.get("datePosted")
    pets_allowed_ld = jsonld.get("petsAllowed")

    # --- HTML feature table (fields not in JSON-LD) ---
    features = _extract_features(html)

    # --- Images ---
    images = _extract_images(html)
    if main_image and main_image not in images:
        images.insert(0, main_image)

    # --- Agent / broker ---
    broker = _extract_agent(html)

    # --- Coordinates ---
    coords = None
    geo = jsonld.get("geo", {}) or {}
    if geo:
        lat = geo.get("latitude")
        lon = geo.get("longitude")
        if lat is not None and lon is not None:
            coords = (float(lat), float(lon))
    if not coords:
        coords = _extract_coordinates(html)

    # --- Feature lookups (English + Dutch label variants) ---
    deposit = _feature_get(features, ["Deposit", "Security deposit", "Borg", "Waarborgsom"])
    interior = _feature_get(features, ["Interior", "Inrichting"])
    available = _feature_get(features, ["Available", "Beschikbaar", "Beschikbaar per"])
    offered_since = _feature_get(features, ["Offered since", "Sinds", "Aangeboden sinds"])
    rental_agreement = _feature_get(
        features, ["Rental agreement", "Contract type", "Contract",
                   "Huurovereenkomst", "Contractvorm", "Contractsoort"]
    )
    energy_label = _feature_get(
        features, ["Energy rating", "Energy label", "Energielabel", "Energieklasse"]
    )
    service_costs = _feature_get(
        features, ["Service costs", "Service charges", "Servicekosten", "Servicekost"]
    )

    # Bedrooms: prefer JSON-LD, fall back to the HTML table.
    if bedrooms is None:
        bedrooms = _feature_get_int(
            features, ["Number of bedrooms", "Bedrooms", "Aantal slaapkamers", "Slaapkamers"]
        )

    # Booleans: prefer JSON-LD, fall back to the HTML table.
    smoking_allowed = _feature_bool(features, ["Smoking allowed", "Roken toegestaan"])
    if pets_allowed_ld is not None:
        pets_allowed = bool(pets_allowed_ld)
    else:
        pets_allowed = _feature_bool(features, ["Pets allowed", "Huisdieren toegestaan"])

    # Object type (from JSON-LD @type or the "Type of house" feature).
    object_type = _resolve_object_type(jsonld, features)

    price_formatted = f"\u20ac{price:,} per month" if price else None

    listing_data = {
        "title": name or street,
        "street": street,
        "city": city,
        "postcode": postcode,
        "neighbourhood": neighbourhood,
        "price": price,
        "price_formatted": price_formatted,
        "currency": currency,
        "living_area": living_area,
        "rooms": rooms,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "year_built": year_built,
        "date_posted": date_posted,
        "description": description,
        "url": url,
        "photos": images,
        "photo_urls": images,
        "photo_count": len(images),
        "energy_label": energy_label,
        "offered_since": offered_since,
        "characteristics": features,
        # Rental-specific
        "deposit": deposit,
        "service_costs": service_costs,
        "interior": interior,
        "available": available,
        "rental_agreement": rental_agreement,
        "smoking_allowed": smoking_allowed,
        "pets_allowed": pets_allowed,
        "offering_type": "rent",
        "object_type": object_type,
    }

    if coords:
        listing_data["latitude"] = coords[0]
        listing_data["longitude"] = coords[1]
        listing_data["coordinates"] = coords

    if broker:
        listing_data["broker"] = broker.get("name")
        listing_data["broker_url"] = broker.get("url")
        listing_data["broker_phone"] = broker.get("phone")

    return Listing(listing_id=listing_id, data=listing_data)


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------

def _extract_jsonld_graph(html: str) -> list[dict]:
    """Extract the @graph array from JSON-LD (used on search pages)."""
    matches = _find_jsonld_blocks(html)
    for data in matches:
        if "@graph" in data:
            return data["@graph"]
    return []


def _extract_jsonld_detail(html: str) -> dict:
    """Extract the listing JSON-LD object from a detail page."""
    wanted = {"RealEstateListing", "House", "Apartment", "Product"}
    for data in _find_jsonld_blocks(html):
        type_val = data.get("@type", "")
        types = type_val if isinstance(type_val, list) else [type_val]
        if any(t in wanted for t in types):
            return data
    return {}


def _find_jsonld_blocks(html: str) -> list[dict]:
    """Return all parsed JSON-LD blocks from the page, ignoring malformed ones."""
    blocks = []
    matches = re.findall(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        re.DOTALL,
    )
    for match in matches:
        try:
            blocks.append(json.loads(match))
        except json.JSONDecodeError:
            continue
    return blocks


# ---------------------------------------------------------------------------
# HTML feature table
# ---------------------------------------------------------------------------

# A <dt>/<dd> pair inside a listing-features list. Tolerant of extra classes,
# a stray space before the closing ``>``, and multi-line ``<span>`` tags.
_FEATURE_PATTERN = re.compile(
    r'<dt\s+class="listing-features__term[^"]*"\s*>(?P<term>.*?)</dt>\s*'
    r'<dd\s+class="listing-features__description[^"]*"\s*>(?P<value>.*?)</dd>',
    re.DOTALL,
)


def _extract_features(html: str) -> dict[str, str]:
    """Extract every feature (term -> value) from the listing feature tables."""
    features = {}
    for match in _FEATURE_PATTERN.finditer(html):
        term = _strip_html(match.group("term"))
        value = _strip_html(match.group("value"))
        if term:
            features[term] = value
    return features


def _strip_html(text: str) -> str:
    """Strip tags, unescape entities, normalise whitespace from an HTML fragment."""
    # Drop UI-only blocks outright (tooltips, icons, scripts) — they never carry
    # listing data and would otherwise leak labels like "More info" into values.
    text = re.sub(r"<button\b[^>]*>.*?</button>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<svg\b[^>]*>.*?</svg>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.DOTALL)

    text = re.sub(r"<li[^>]*>", ", ", text)   # list items -> comma-separated
    text = re.sub(r"</li>", "", text)
    text = re.sub(r"<br\s*/?>", " ", text)     # line breaks -> space
    text = re.sub(r"<[^>]+>", "", text)        # strip remaining tags
    text = html_lib.unescape(text)
    text = text.replace("\xa0", " ")           # non-breaking space -> space
    text = re.sub(r"\s+", " ", text).strip()
    # Collapse whitespace around commas introduced by <li> joins. Using \s+
    # (not \s*) leaves thousands separators like "€9,000" untouched, since the
    # comma there has no leading whitespace.
    text = re.sub(r"\s+,\s*", ", ", text)
    text = text.strip(" ,")
    return text


# ---------------------------------------------------------------------------
# Feature lookups (with language variants)
# ---------------------------------------------------------------------------

def _feature_get(features: dict[str, str], labels: list[str]) -> Optional[str]:
    """Return the first non-empty feature value matching any of ``labels``."""
    for label in labels:
        for key, value in features.items():
            if key.strip().lower() == label.lower():
                if value:
                    return value
    return None


def _feature_get_int(features: dict[str, str], labels: list[str]) -> Optional[int]:
    value = _feature_get(features, labels)
    if value is None:
        return None
    return _as_int(value)


def _feature_bool(features: dict[str, str], labels: list[str]) -> Optional[bool]:
    value = _feature_get(features, labels)
    if value is None:
        return None
    v = value.lower()
    if v in ("yes", "ja", "allowed", "toegestaan", "in consultation", "in overleg"):
        return True
    if v in ("no", "nee", "not allowed", "niet toegestaan"):
        return False
    return None


def _as_int(value) -> Optional[int]:
    """Best-effort integer coercion; returns None on failure."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"-?\d+", str(value))
    if match:
        return int(match.group(0))
    return None


def _resolve_object_type(jsonld: dict, features: dict[str, str]) -> str:
    """Derive the property type from JSON-LD @type or the HTML feature table."""
    type_val = jsonld.get("@type", "")
    types = type_val if isinstance(type_val, list) else [type_val]
    if "House" in types:
        return "house"
    if "Apartment" in types:
        return "apartment"
    type_of_house = _feature_get(features, ["Type of house", "Type of apartment", "Type woning", "Soort woning"])
    if type_of_house:
        return type_of_house.lower()
    return "apartment"


# ---------------------------------------------------------------------------
# Images / agent / coordinates
# ---------------------------------------------------------------------------

def _extract_images(html: str) -> list[str]:
    """Extract all listing images from HTML."""
    images = set()
    pattern = r'(https://casco-media-prod[^"&\s]+\.(?:jpg|png|webp))'
    for img in re.findall(pattern, html):
        if "width=600" in img or "width=" not in img:
            images.add(img.replace("&amp;", "&"))
    return list(images)[:20]


def _extract_agent(html: str) -> Optional[dict]:
    """Extract agent information from HTML."""
    agent_url = None
    agent_name = None
    agent_phone = None

    url_match = re.search(r'href="(/real-estate-agent[^"]+)"', html)
    if url_match:
        agent_url = f"https://www.pararius.com{url_match.group(1)}"

    name_match = re.search(r'agent-summary__title-link"[^>]*>([^<]+)', html)
    if name_match:
        agent_name = name_match.group(1).strip()

    phone_match = re.search(r'tel:([^"]+)', html)
    if phone_match:
        agent_phone = phone_match.group(1)

    if agent_url or agent_name:
        return {"name": agent_name, "url": agent_url, "phone": agent_phone}
    return None


def _extract_coordinates(html: str) -> Optional[tuple[float, float]]:
    """Extract map coordinates from HTML (fallback when JSON-LD has no geo)."""
    match = re.search(r'data-latitude="([^"]+)"[^>]*data-longitude="([^"]+)"', html)
    if match:
        return (float(match.group(1)), float(match.group(2)))

    match = re.search(r'data-lat="([^"]+)"[^>]*data-lon="([^"]+)"', html)
    if match:
        return (float(match.group(1)), float(match.group(2)))

    match = re.search(r'"lat":\s*([\d.]+).*?"lon":\s*([\d.]+)', html)
    if match:
        return (float(match.group(1)), float(match.group(2)))

    return None
