"""Filesystem state, validated source definitions and calendar maintenance."""
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
PACIFIC = ZoneInfo('America/Los_Angeles')


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text('utf-8'))


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode('utf-8')
    if path.exists() and path.read_bytes() == content:
        return
    with NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        temp.write(content)
    os.replace(temp.name, path)


def json_out(path, data):
    write(path, json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n')


def catalog():
    sources = yaml.safe_load((ROOT / 'sources.yaml').read_text())
    ids, urls = set(), set()
    for s in sources:
        if any(not s.get(key) for key in ('id','name','agency','category','url','notes')):
            raise ValueError('Missing required source metadata')
        if not re.fullmatch(r'[a-z0-9-]+',s['id']) or s['id'] in ids or s['url'] in urls:
            raise ValueError(f"Invalid or duplicate source: {s['id']}")
        if urlsplit(s['url']).scheme != 'https':
            raise ValueError(f"Use an official HTTPS URL: {s['id']}")
        ids.add(s['id'])
        urls.add(s['url'])
    return sources


def config():
    return yaml.safe_load((ROOT / 'config.yaml').read_text())


def snap_path(s):
    return DATA/'snapshots'/(s['id'] + '.json')


def signature(*parts):
    return hashlib.sha256(json.dumps(parts,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]


def date_text(value):
    return date.fromisoformat(str(value)).strftime('%b %-d, %Y')


def calendar(sources, state):
    """Only roll a date forward when a reviewed, narrowly scoped rule finds ONE explicit date."""
    rows = yaml.safe_load((DATA/'deadlines.yaml').read_text()) or []
    by_url = {s['url']:s for s in sources}
    output = []
    date_re = r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b'
    for row in rows:
        row = dict(row, date=str(row['date']),date_captured=str(row['date_captured']))
        source = by_url.get(row['source_url'])
        status = state['health'].get(source['id'],{}) if source else {}
        if row.get('live_evidence') and (not source or row['live_evidence'] not in read_json(snap_path(source), {}).get('lines', [])):
            continue
        row['check'] = ''
        if source and not status.get('ok'):
            row['check'] = 'Source check failed. Confirm the date with the publisher.'
        if row.get('anchor') and source and status.get('last_success'):
            snap = read_json(snap_path(source),{})
            lines = snap.get('lines',[])
            if row.get('section'):
                try:
                    lines = lines[lines.index(row['section'])+1:lines.index(row['until'])]
                except ValueError:
                    lines = []
            matches = []
            for i,line in enumerate(lines):
                if re.search(row['anchor'],line,re.I):
                    window = ' '.join(lines[i:i+row.get('window',2)])
                    matches.extend(re.findall(date_re,window,re.I))
            if len(matches) != 1:
                # Withdraw from upcoming dates when the authoritative timeline drops a dated event.
                continue
            found = datetime.strptime(matches[0],'%B %d, %Y').date().isoformat()
            if found != row['date']:
                row['date'] = found
                row['date_captured'] = status.get('last_change') or status['last_success'][:10]
        elif source and status.get('last_change','') > row['date_captured']:
            row['check'] = 'Publisher changed this source after capture. Recheck the linked date.'
        output.append(row)
    return sorted(output,key=lambda d:(d['date'],d['program'],d['event']))
