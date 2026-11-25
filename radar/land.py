"""Read HCD's statewide NOA list and companion map without geocoding requests."""
import csv
import hashlib
import io
import json
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .extract import safe_url


# CSV heading / GIS field / output key. Both are HCD's data.
FIELDS = (
    ("Parent Case", "PARENT_CASE", "case"),
    ("Local Agency", "LOC_AGENCY", "agency"),
    ("APN", "APN", "apn"),
    ("Date Notice Issued", "DATE_NOTICE_ISSUED", "notice_date"),
    ("NOA Due Date", "NOA_DUE_DATE", "due_date"),
    ("NOA Status", "NOA_STATUS", "status"),
    ("Notice Website Link", "NOTICE_WEBSITE_LINK", "url"),
    ("Address", "ADDRESS", "address"),
    ("City", "CITY", "city"),
    ("x", "X", "longitude"),
    ("y", "Y", "latitude"),
    ("Parcel Size (Gross Acres)", "PARCEL_SIZE_GROSS_ACRES", "acreage"),
    ("Notice Contact Information- Concatenated", "NOTICE_CONTACT_INFO", "contact"),
)


def _clean(value):
    return " ".join(str(value or "").split())


def _key(value):
    simple = unicodedata.normalize("NFKD", value.casefold())
    return "".join(c for c in simple if c.isalnum())


@lru_cache(maxsize=1)
def _reference():
    geo = Path(__file__).with_name("geography")
    index = json.loads((geo / "index.json").read_text())
    polygons = []
    for county in index["counties"]:
        filename = county.lower().replace(" ", "-") + ".json"
        polygons.extend(json.loads((geo / filename).read_text()))
    return {_key(k):v for k,v in index["cities"].items()}, polygons


def _in_ring(x, y, ring):
    inside = False
    x0, y0 = ring[-1]
    for x1, y1 in ring:
        if (y0 > y) != (y1 > y) and x < x0 + (x1 - x0) * (y - y0) / (y1 - y0):
            inside = not inside
        x0, y0 = x1, y1
    return inside


@lru_cache(maxsize=10000)
def _point_county(longitude, latitude):
    try:
        x, y = float(longitude), float(latitude)
    except (ValueError, TypeError):
        return ""
    for county, (west, south, east, north), rings in _reference()[1]:
        if west <= x <= east and south <= y <= north:
            if _in_ring(x, y, rings[0]) and not any(_in_ring(x, y, hole) for hole in rings[1:]):
                return county
    return ""


def _as_date(value):
    if not value:
        return ""
    for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"HCD changed a date format: {value[:45]!r}")


def _normalize(row):
    row["notice_date"] = _as_date(row["notice_date"])
    row["due_date"] = _as_date(row["due_date"])
    if not row["case"]:
        raise ValueError("HCD returned a parcel without a parent case identifier.")
    city = row["city"]
    address = row["address"]
    row["site"] = ", ".join(v for v in (address, city) if v)
    if address and city and _key(city) in _key(address):
        row["site"] = address
    county = _point_county(row["longitude"], row["latitude"])
    method = "site coordinates" if county else ""
    if not county:
        county = _reference()[0].get(_key(city), "")
        method = "site city" if county else ""
    row["county"], row["county_method"] = county, method
    if row["url"].lower().startswith("www."):
        row["url"] = "https://" + row["url"]
    row["url"] = safe_url(row["url"])
    row.pop("contact", None)  # Public repository: link to HCD for agency contacts.
    return row


def parse_land(body: bytes, kind: str) -> list[dict]:
    """Return statewide parcel rows, including archives and unassigned locations."""
    if kind == "land_csv":
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = body.decode("cp1252")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        fields = {_key(name): name for name in reader.fieldnames or []}
        # CKAN DataStore dumps expose machine names for a few headings.
        lookup = {key: fields.get(_key(header)) for header, _, key in FIELDS}
        rows = reader
    elif kind == "land_map":
        collection = json.loads(body)
        if collection.get("error") or collection.get("exceededTransferLimit"):
            raise ValueError("HCD map API error or incomplete result.")
        lookup = {key: code for _, code, key in FIELDS}
        features = collection["features"]
        if not features or not set(lookup.values()) <= set(features[0]["attributes"]):
            raise ValueError("HCD map has no rows or has changed fields.")
        rows = (item["attributes"] for item in features)
    else:
        raise ValueError(f"Unknown HCD input format {kind}")
    if not all(lookup.values()):
        missing = ", ".join(k for k, v in lookup.items() if not v)
        raise ValueError(f"HCD changed its notice fields: {missing}")
    parsed = [_normalize({k: _clean(row[col]) for k, col in lookup.items()}) for row in rows]
    if not parsed or not any(row["notice_date"] for row in parsed):
        raise ValueError("HCD has no dated notices.")
    return parsed


def notice_link(row, source):
    """Prefer the agency's parcel-specific notice, then HCD's public, case-filtered CSV."""
    direct = safe_url(row.get("url", ""))
    if direct and urlsplit(direct).path.strip("/"):
        return direct
    parts = urlsplit(source["url"])
    if source.get("case_filter_field") and row.get("case"):
        query = parse_qsl(parts.query, keep_blank_values=True)
        query.append(("filters", json.dumps({source["case_filter_field"]: row["case"]}, separators=(",", ":"))))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    return source.get("public_url", source["url"])


def land_key(row):
    """Parent case + APN distinguishes parcels and repeat offerings of the same land."""
    parcel = _key(row["apn"])
    if parcel in ("", "na", "tbd", "none", "unknown"):
        parcel = "|".join((_key(row["site"]), row["longitude"], row["latitude"]))
    return hashlib.sha256((row["case"].upper() + "|" + parcel).encode()).hexdigest()[:24]


def merge_land(csv_rows, map_rows):
    """Use the active map's nonblank updates, retaining historical CSV parcels."""
    merged = {}
    for record in [*csv_rows, *map_rows]:
        key = land_key(record)
        prior = merged.setdefault(key, dict(record))
        # For a duplicated CSV row, the more descriptive location survives even
        # if the duplicate contains only a city. A new map address can replace it.
        if prior["address"] and not record["address"]:
            record = {**record, "site": prior["site"]}
        prior.update((k, v) for k, v in record.items() if v)
    return list(merged.values())
