"""Read the public meeting index used by Santa Maria's Block Grants Advisory Committee."""
import json
from urllib.parse import urlsplit

from .extract import clean, safe_url
from .net import MonitorError


def agenda_snapshot(body, url):
    """Extract the most recent page of city-published meetings and attachments."""
    try:
        records = json.loads(body)["d"]["Meetings"]
    except (ValueError, TypeError, KeyError) as exc:
        raise MonitorError("Public meeting response is missing its agenda list") from exc
    if not isinstance(records, list) or not records:
        raise MonitorError("Public meeting index contains no meetings")

    lines = []
    documents = {}
    links = {}
    hostname = urlsplit(url).hostname
    for meeting in records:
        if not isinstance(meeting, dict) or meeting.get("MeetingType") != "Block Grants Advisory Committee":
            raise MonitorError("Unexpected commission in the public meeting index")
        date = clean(meeting.get("FormattedStart"))
        materials = meeting.get("MeetingLinks")
        if "MeetingLinks" in meeting and materials is None and meeting.get("HasLinks") is False:
            materials = []
        if not date or not isinstance(materials, list):
            raise MonitorError("A meeting has lost its date or published materials field")
        location = clean(meeting.get("LocationName"))
        lines.append(" · ".join(filter(None, (date, location))))
        for material in materials:
            if not isinstance(material, dict) or not material.get("Url") or not material.get("Title"):
                raise MonitorError("Unexpected format for published meeting materials")
            link = safe_url(material["Url"], url)
            if not link or urlsplit(link).hostname != hostname:
                continue
            label = f"{meeting.get('DateLong') or date} · {clean(material['Title'])}"
            links[link] = label
            lines.append(label)
            if material.get("Format", "").lower().lstrip(".") in {"pdf", "xlsx", "xls", "docx", "doc"}:
                documents[link] = label
    if not documents:
        raise MonitorError("The meeting index contains no published agenda documents")
    return {
        "title": "Santa Maria Block Grants Advisory Committee",
        "lines": lines,
        "documents": dict(sorted(documents.items())),
        "links": dict(sorted(links.items())),
    }


def legistar_snapshot(body, url, source=None):
    """Read a public legislative service’s matching housing funding matters."""
    try:
        records = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise MonitorError("County legislative service returned invalid JSON") from exc
    if not isinstance(records, list) or not records:
        raise MonitorError("County legislative service returned no matching matters")

    lines = []
    links = {}
    matters_url = url.partition("?")[0].rstrip("/")
    for matter in records:
        if not isinstance(matter, dict) or not isinstance(matter.get("MatterId"), int):
            raise MonitorError("County legislative response is missing the matter identifier")
        title = clean(matter.get("MatterTitle"))
        number = clean(matter.get("MatterFile"))
        if not title or not number:
            raise MonitorError("County legislative response is missing a file number or title")
        if matter.get("MatterRestrictViewViaWeb"):
            continue
        date = clean(matter.get("MatterAgendaDate"))[:10]
        status = clean(matter.get("MatterStatusName"))
        lines.append(" · ".join(filter(None, (number, date, status, title))))
        target = f"{matters_url}/{matter['MatterId']}"
        if source and source.get('legistar_site') and matter.get('MatterGuid'):
            target = f"{source['legistar_site']}/LegislationDetail.aspx?ID={matter['MatterId']}&GUID={matter['MatterGuid']}"
        links[target] = f"File {number} · {title[:140]}"
    if not lines:
        raise MonitorError("County legislative service returned no public matters")
    return {
        "title": (source or {}).get("name", "Santa Barbara County housing funding agenda items"),
        "lines": lines,
        "documents": {},
        "links": dict(sorted(links.items())),
    }
