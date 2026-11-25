"""Render reviewed developer opportunities against the latest official snapshots."""
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from html import escape

import yaml

from .extract import safe_url
from .state import date_text, read_json, snap_path


def normalized(text):
    folded = unicodedata.normalize('NFKC', text).casefold()
    return ' '.join(re.sub(r'[^\w%$]+', ' ', folded).split())


def evidence_matches(round_, snapshots, health, today):
    if 'issued' in round_ and 'confirm_days' in round_:
        age = (date.fromisoformat(today) - date.fromisoformat(str(round_['issued']))).days
        if age < 0 or age > round_['confirm_days']:
            return False
    if round_.get('starts') and str(round_['starts']) > today:
        return False
    if round_.get('until') and str(round_['until']) < today:
        return False
    for source_id, phrases in round_.get('evidence', {}).items():
        if not health.get(source_id, {}).get('ok'):
            return False
        text = normalized(' '.join(snapshots.get(source_id, {}).get('lines', [])))
        if not phrases or not all(normalized(phrase) in text for phrase in phrases):
            return False
        if any(normalized(phrase) in text for phrase in round_.get('stop', [])):
            return False
    return bool(round_.get('evidence'))


# Only parse a single issuer-labelled open row or an explicit invitation. Never combine
# amounts, dates or status from neighbouring programs on a multi-round listing.
DATE = r'(?:[A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+20\d{2}|\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{2}-\d{2})'
DUE = re.compile(r'(?:deadline|applications? due|proposals? due|apply by|applications? (?:close|accepted until))'
                 r'[^.;|]{0,36}?(' + DATE + r')', re.I)
OPEN = re.compile(r'\|\s*open\s*\||(?:currently|now) accepting (?:developer |owner )?(?:applications|proposals)|'
                  r'(?:applications|proposals) (?:are (?:currently |now )?open|are being accepted)', re.I)
EXCLUDE = re.compile(r'wait.?list|waiting list|public comment|no longer|not (?:currently |now )?(?:open|accepting)|'
                     r'closed|cancel[le]d|withdrawn|tenant applications|seeking (?:tenants|residents)|opens? on', re.I)
PBV = re.compile(r'project[ -]based (?:housing )?vouchers?|\bPBVs?\b', re.I)
FUNDING = re.compile(r'\b(?:NOFA|HOME|CDBG|PLHA)\b|affordable housing|housing trust fund', re.I)


def intake_offers(section, row, snapshots, health, today):
    offers = []
    for sid in row.get('intake', []):
        if not health.get(sid, {}).get('ok'):
            continue
        for line in snapshots.get(sid, {}).get('lines', []):
            if not OPEN.search(line) or EXCLUDE.search(line):
                continue
            subject = PBV if section == 'pbv' else FUNDING
            if not subject.search(line) or (section != 'pbv' and PBV.search(line)):
                continue
            deadline = DUE.search(line)
            until = ''
            if deadline:
                raw = re.sub(r'(?<=\d)(?:st|nd|rd|th)\b|[,.]', '', deadline[1], flags=re.I)
                for fmt in ('%B %d %Y', '%b %d %Y', '%m/%d/%Y', '%Y-%m-%d'):
                    try:
                        until = datetime.strptime(raw, fmt).date().isoformat()
                        break
                    except ValueError:
                        continue
                if not until or until < today:
                    continue
            elif re.search(DATE, line, re.I):
                # A dated paragraph without an attributable deadline needs review.
                continue
            value_pattern = (r'(?:up to )?[\d,]+ (?:project[ -]based vouchers?|PBVs?)' if section == 'pbv'
                             else r'(?:up to )?\$[\d,.]+(?: (?:million|billion))?')
            amount = re.search(value_pattern, line, re.I)
            offers.append(dict(name=line.split('|')[0].strip() if '|' in line else row['name'],
                               deadline=date_text(until) if until else ('Rolling' if 'rolling' in line.lower() else ''),
                               until=until, value=amount[0] if amount else '', evidence={sid:[line]}, source=sid))
    return offers


def add_intake_deadlines(path, sources, health, today, deadline_path):
    if not path.exists():
        return
    registry = yaml.safe_load(path.read_text()) or {}
    catalog = {s['id']:s for s in sources}
    old = yaml.safe_load(deadline_path.read_text()) or []
    known = {(str(r['date']), r['source_url'], r['program']) for r in old}
    fresh = []
    for section, rows in registry.items():
        for row in rows:
            if not row.get('intake'):
                continue
            snapshots = {sid:read_json(snap_path(catalog[sid]), {}) for sid in row['intake'] if sid in catalog}
            for offer in intake_offers(section, row, snapshots, health, today):
                if not offer['until']:
                    continue
                sid = offer['source']
                url = catalog[sid]['url']
                key = (offer['until'], url, row['name'])
                if key in known:
                    continue
                known.add(key)
                fresh.append(dict(program=row['name'], event=offer['name'] + ' application deadline',
                                  date=offer['until'], source_url=url, date_captured=today,
                                  live_evidence=offer['evidence'][sid][0]))
    if fresh:
        with deadline_path.open('a', encoding='utf-8') as stream:
            stream.write('\n' + yaml.safe_dump(fresh, sort_keys=False, allow_unicode=True, width=110))


def sections(path, sources, health, today):
    registry = yaml.safe_load(path.read_text()) if path.exists() else {}
    catalog = {s['id']: s for s in sources}
    used = {sid for programs in registry.values() for row in programs for sid in row.get('sources', [])}
    snapshots = {sid: read_json(snap_path(catalog[sid]), {}) for sid in used if sid in catalog}
    result = {}
    for section, programs in registry.items():
        counties = defaultdict(list)
        for row in programs:
            ids = row.get('sources', [])
            refs = [catalog[sid] for sid in ids if sid in catalog]
            offers = [offer for offer in row.get('rounds', []) if evidence_matches(offer, snapshots, health, today)]
            reviewed = {sid for offer in offers for sid in offer['evidence']}
            offers.extend(offer for offer in intake_offers(section, row, snapshots, health, today)
                          if offer['source'] not in reviewed)
            counties[row['county']].append((row, refs, offers))
        groups = []
        for county, entries in sorted(counties.items()):
            opened = sum(len(offers) for _, _, offers in entries)
            label = f' · {opened} open' if opened else ''
            items = []
            for row, refs, offers in entries:
                chunks = [f'<article class="program-row"><h3>{escape(row["name"])}</h3>']
                if offers:
                    for offer in offers:
                        details = [offer['name'], offer.get('value') or ('Voucher count not stated' if section == 'pbv' else 'Amount not stated'),
                                   offer.get('deadline') or 'Deadline not stated', offer.get('note')]
                        chunks.append('<p><strong>Open</strong> · ' + escape(' · '.join(filter(None, details))) + '</p>')
                else:
                    empty = 'No open solicitation shown' if section == 'pbv' else 'No open round shown'
                    chunks.append('<p>' + (empty if any(health.get(s['id'], {}).get('ok') for s in refs) else 'Coverage unavailable') + '</p>')
                for notice in row.get('announcements', []):
                    if evidence_matches(notice, snapshots, health, today):
                        chunks.append('<p>' + escape(notice['text']) + '</p>')
                if row.get('note'):
                    chunks.append('<p class="meta">' + escape(row['note']) + '</p>')
                links = []
                for s in refs:
                    url = safe_url(s.get('public_url', s['url']))
                    if s.get('legistar_site'):
                        docket = snapshots.get(s['id'], {})
                        recent = docket.get('lines', [])[:2]
                        for line in recent:
                            number = line.split(' · ',1)[0]
                            prefix = f'File {number} · '
                            for target, link_text in docket.get('links', {}).items():
                                if link_text.startswith(prefix) and safe_url(target):
                                    links.append(f'<a href="{escape(target, quote=True)}">{escape(link_text)}</a>')
                                    break
                    if url:
                        links.append(f'<a href="{escape(url, quote=True)}">{escape(row.get("labels", {}).get(s["id"],s["name"]))}</a>')
                changes = [health.get(s['id'], {}).get('last_change', '') for s in refs]
                stamp = max(changes, default='')
                last = date_text(stamp) if stamp else ('No change since first capture' if refs else 'Unverified')
                if reader := row.get('reader_link'):
                    if url := safe_url(reader['url']):
                        links.append(f'<a href="{escape(url, quote=True)}">{escape(reader["label"])}</a>')
                if links:
                    chunks.append('<p class="program-links">' + ' · '.join(links) + '</p>')
                chunks.append('<small>Last change: ' + last + '</small></article>')
                items.append(''.join(chunks))
            groups.append('<details class="health-row"><summary><strong>' + escape(county) + '</strong> (' +
                          str(len(entries)) + ')' + label + '</summary>' + ''.join(items) + '</details>')
        result[section] = ''.join(groups)
    return result
