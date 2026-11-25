"""Run from the repository root with python -m radar.collect."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

import yaml

from .extract import differences, file_snapshot, snapshot_html
from .land import land_key, merge_land, notice_link, parse_land
from .meetings import agenda_snapshot, legistar_snapshot
from .net import Fetcher, MonitorError
from .state import DATA, PACIFIC, ROOT, catalog, config, json_out, read_json, signature, snap_path, write


def check_structure(old, new, previous, today):
    if not old:
        return
    if 'rows' in new:
        suspect = new['raw_rows'] < old['raw_rows'] * 0.7
        fingerprint = signature([land_key(r) for r in new['rows']])
    else:
        before = sum(map(len,old['lines']))
        after = sum(map(len,new['lines']))
        suspect = ((before > 500 and after < .30*before)
                   or (len(old['documents']) >= 5 and not new['documents']))
        fingerprint = signature(new['lines'],new['documents'])
    if suspect and not (previous.get('candidate') == fingerprint and previous.get('attempt_day') != today):
        error = MonitorError("Large drop in readable content; waiting for a second daily observation")
        error.candidate = fingerprint
        raise error


def fetch_source(source, previous, fetch, stamp, counties=None):
    today = stamp[:10]
    url = source['url']
    if previous.get('attempt_day') == today and previous.get('url') == url:
        return None
    old = read_json(snap_path(source))
    if previous.get('url') and previous['url'] != url:
        old = None
    headers = {}
    if old and previous.get('ok') and previous.get('url') == url:
        if previous.get('etag'):
            headers['If-None-Match'] = previous['etag']
        if previous.get('modified'):
            headers['If-Modified-Since'] = previous['modified']
    health = {**previous, 'attempt_day':today, 'last_attempt':stamp, 'url':url}
    try:
        r = fetch.get(url,headers)
        kind = source.get('kind','html')
        new = None
        if r.status != 304:
            if kind in ('land_csv','land_map'):
                rows = parse_land(r.body,kind)
                allowed = counties if counties is not None else set(config()['counties'])
                new = {'raw_rows':len(rows),'latest_statewide':max(r['notice_date'] for r in rows),
                       'unassigned':sum(not r['county'] for r in rows),
                       'rows':merge_land([r for r in rows if r['county'] in allowed],[])}
            elif kind in ('pdf','xlsx','docx'):
                new = file_snapshot(r.body,source)
            elif kind == 'legistar':
                new = legistar_snapshot(r.body,r.url)
            elif kind == 'meetings':
                new = agenda_snapshot(r.body,r.url)
            else:
                new = snapshot_html(r.body,r.url,r.headers,source)
            check_structure(old,new,previous,today)
        elif not old:
            raise MonitorError("Publisher returned 304 without a prior snapshot")
        health.update(ok=True,last_success=r.observed_at or stamp,http=r.status,error='',candidate='',
                      etag=r.headers.get('etag',previous.get('etag','') if r.status==304 else ''),
                      modified=r.headers.get('last-modified',previous.get('modified','') if r.status==304 else ''))
        return health,old,new
    except Exception as exc:
        health.update(ok=False,error=f'{type(exc).__name__}: {str(exc)[:250]}',candidate=getattr(exc,'candidate',''))
        return health,old,None


def persist_land(new, old, source, state, counties, stamp, events):
    today = stamp[:10]
    prior = {land_key(r):r for r in old['rows']} if old else {}
    seen = state.setdefault('first_seen',{})
    for row in new['rows']:
        key = land_key(row)
        unseen = key not in seen
        seen.setdefault(key,today)
        if row['county'] not in counties or not old:
            continue
        if unseen or (key in prior and prior[key] != row):
            is_new = unseen
            changed = [f"{field}: {prior[key][field] or 'unlisted'} → {row[field] or 'unlisted'}"
                       for field in ('site','apn','acreage','notice_date','due_date','status','url','county','agency')
                       if not is_new and prior[key].get(field)!=row.get(field)]
            if is_new or changed:
                events.append({'id':signature(source['id'],key,stamp,row), 'at':stamp,
                               'source':source['id'],'type':'land' if is_new else 'land_update',
                               'title':row['site'] or row['apn'] or row['case'],'county':row['county'],
                               'case':row['case'],'agency':row['agency'],'notice_date':row['notice_date'],
                               'url':notice_link(row,source),'added':' · '.join(changed)[:500]})
    if not old:
        state['land_baseline'] = today


def collect(sources=None, now=None, fetcher=None):
    sources = sources or catalog()
    conf = config()
    stamp = (now or datetime.now(PACIFIC)).isoformat(timespec='seconds')
    today = stamp[:10]
    state = read_json(DATA/'state.json',{'health':{}, 'baseline':today})
    history = read_json(DATA/'changes.json',[])
    ledger = read_json(DATA/'fetch-ledger.json',{'requests':{},'robots':{}})
    fetch = fetcher or Fetcher(sources,today,ledger)
    if fetcher:
        ledger = fetcher.ledger
    fresh_events = []
    def run(source):
        return fetch_source(source,state['health'].get(source['id'],{}),fetch,stamp,set(conf['counties']))
    def save(source, result):
        if result is None:
            return
        h,old,new = result
        if new is not None:
            if 'rows' in new:
                persist_land(new,old,source,state,set(conf['counties']),stamp,fresh_events)
            else:
                delta = differences(old,new) if old else None
                if delta:
                    fresh_events.append({'id':signature(today,source['id'],delta),'at':stamp,'source':source['id'],
                                         'type':'change','title':source['name'],'url':source.get('public_url',source['url']),**delta})
            if old != new:
                if old:
                    h['last_change'] = today
                json_out(snap_path(source),new)
        state['health'][source['id']] = h
        print(source['id'], 'OK' if h['ok'] else h['error'], flush=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for source, result in zip(sources,pool.map(run,sources)):
            save(source,result)

    # A parent publishes the exact current-year URL. Keep earlier award pages and
    # append verified new annual sources without reformatting a user's YAML edits.
    known = {s['url'] for s in sources}
    for parent in list(sources):
        if not parent.get('discover_year') or not state['health'][parent['id']].get('ok'):
            continue
        snapshot = read_json(snap_path(parent),{})
        for url in snapshot.get('links',{}):
            if url in known or urlsplit(url).netloc != urlsplit(parent['url']).netloc:
                continue
            match = re.search(parent['discover_year'],url)
            if not match:
                continue
            yr = match.group(1)
            dynamic = {'id':f"{parent['agency'].lower()}-annual-{yr}", 'agency':parent['agency'],
                       'category':'Applications and awards','name':f'{yr} application and award lists',
                       'url':url,'notes':f"Current-year link verified on {parent['name']}."}
            if any(s['id']==dynamic['id'] for s in sources):
                continue
            result = run(dynamic)
            if result and result[0]['ok']:
                save(dynamic,result)
                with (ROOT/'sources.yaml').open('a',encoding='utf-8') as f:
                    f.write('\n'+yaml.safe_dump([dynamic],sort_keys=False,allow_unicode=True))
                known.add(url)
                sources.append(dynamic)

    cutoff = (date.fromisoformat(today) - timedelta(days=89)).isoformat()
    history = [e for e in history if e['at'][:10]>=cutoff]
    unique = {e['id']:e for e in [*history,*fresh_events]}
    history = sorted(unique.values(),key=lambda e:(e['at'],e['id']), reverse=True)
    state['as_of'] = max((state['health'][s['id']]['last_attempt'] for s in sources),default=stamp)
    state['total'] = len(sources)
    state['failed'] = sum(not state['health'][s['id']]['ok'] for s in sources)
    ledger['requests'] = {url:v for url,v in ledger.get('requests',{}).items() if v['date']==today}
    json_out(DATA/'fetch-ledger.json',ledger)
    json_out(DATA/'state.json',state)
    json_out(DATA/'changes.json',history)
    print(f"{len(sources)-state['failed']}/{len(sources)} healthy; {len(fresh_events)} changes",flush=True)
    return state


if __name__ == '__main__':
    result = collect()
    raise SystemExit(2 if result['failed']*10 > result['total']*3 else 0)
