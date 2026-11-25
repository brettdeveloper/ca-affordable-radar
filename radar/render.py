"""Render a self-contained static report and Atom feed using committed snapshots."""
import shutil
import xml.etree.ElementTree as X
from collections import defaultdict
from datetime import date, datetime
from html import escape
from string import Template

from .extract import safe_url
from .land import land_key, notice_link
from .opportunities import sections
from .state import DATA, PACIFIC, ROOT, calendar, catalog, config, date_text, read_json, snap_path, write


def e(value):
    return escape(str(value or ''),quote=True)


def link(url,label):
    url = safe_url(url)
    return f'<a href="{e(url)}">{e(label)}</a>' if url else e(label)


def bullets(mapping):
    return '<ul>'+''.join('<li>'+link(u,v)+'</li>' for u,v in mapping.items())+'</ul>'


def change_html(event):
    body = [f'<article class="change" id="event-{e(event["id"])}">',
            f'<p class="agency">{e(date_text(event["at"][:10]))} · {e(event.get("agency") or event.get("source"))}</p>',
            f'<h3>{link(event["url"],event["title"])}</h3>']
    if event.get('added'):
        body.append('<p><strong>Added</strong> '+e(event['added'])+'</p>')
    if event.get('removed'):
        body.append('<p><strong>Removed</strong> '+e(event['removed'])+'</p>')
    for field,label in [('new_docs','New documents'),('removed_docs','Removed documents'),('new_links','Other new links'),('removed_links','Other removed links')]:
        if records := event.get(field):
            body.append(f'<details><summary>{label} ({len(records)})</summary>{bullets(records)}</details>')
    if not any(event.get(f) for f in ('added','removed','new_docs','removed_docs','new_links','removed_links')):
        body.append('<p>The publisher replaced the file at the same URL.</p>')
    return ''.join(body)+'</article>'


def land_badge(first, notice, baseline, today):
    if not first:
        return ''
    seen = date.fromisoformat(first)
    if first == baseline and (not notice or not 0 <= (seen - date.fromisoformat(notice)).days <= 14):
        return ''
    if not 0 <= (date.fromisoformat(today) - seen).days < 14:
        return ''
    return f'<span class="badge" data-first-seen="{e(first)}" title="First observed {e(first)}">NEW</span>'


def land_card(row, first, today, source, baseline):
    missing = 'Not listed'
    when = row['notice_date']
    details = [('APN',row['apn']),('Acres',row['acreage']),('Notice issued',date_text(when) if when else ''),
               ('Response date',date_text(row['due_date']) if row['due_date'] else ''),
               ('HCD status',row['status']),('HCD case',row['case'])]
    items = ''.join(f'<div><dt>{label}</dt><dd>{e(val or missing)}</dd></div>' for label,val in details)
    badge = land_badge(first, when, baseline, today)
    hidden = '' if row['status'].casefold() == 'active' else ' hidden'
    target = notice_link(row,source)
    parcel_link = link(target,'Published notice' if target == row.get('url') else 'HCD case and agency contact (CSV)')
    site = row['site'] or ('APN '+row['apn'] if row['apn'] else row['case'])
    city = row['city']
    if city and city.islower() and site.endswith(', '+city):
        site = site[:-len(city)] + city.title()
    return (f'<article class="parcel" data-county="{e(row["county"])}" data-status="{e(row["status"])}" data-notice-date="{e(when)}"{hidden}><div class="parcel-heading"><div>'
            f'<p class="agency">{e(row["agency"] or "Agency not listed")} · {e(row["county"])} County</p>'
            f'<h3>{e(site)}</h3></div>{badge}</div>'
            f'<dl class="parcel-meta">{items}</dl><p class="meta">{parcel_link}</p></article>')


def atom(events, url, stamp):
    ns='http://www.w3.org/2005/Atom'
    X.register_namespace('',ns)
    def tag(el,name,value=None,**attrs):
        result = X.SubElement(el,'{'+ns+'}'+name,attrs)
        result.text = value
        return result
    feed = X.Element('{'+ns+'}feed')
    tag(feed,'id',url); tag(feed,'title','CA Affordable Housing Radar'); tag(feed,'updated',stamp)
    tag(feed,'link',href=url); tag(feed,'link',rel='self',href=url+'feed.xml')
    tag(tag(feed,'author'),'name','CA Affordable Housing Radar')
    for event in events:
        entry=tag(feed,'entry')
        tag(entry,'id',url+'#event-'+event['id'])
        prefix = {'land':'New surplus land','land_update':'Surplus land update','change':'Source change'}[event['type']]
        tag(entry,'title',prefix+' · '+event['title']); tag(entry,'updated',event['at'])
        tag(entry,'link',href=safe_url(event['url']) or url)
        description = ' '.join(filter(None,[event.get('agency'),event.get('county'),event.get('notice_date'),
                           event.get('added'),event.get('removed')]))
        tag(entry,'summary',description or 'The source or its published materials changed.')
        for u,label in event.get('new_docs',{}).items():
            if safe_url(u):
                tag(entry,'link',href=u,rel='related',title=label)
    return X.tostring(feed,encoding='utf-8',xml_declaration=True)


def render():
    sources = catalog()
    lookup = {s['id']:s for s in sources}
    conf,state = config(),read_json(DATA/'state.json')
    stamp=state['as_of']
    today=stamp[:10]
    health=state['health']
    dates=[r for r in calendar(sources,state) if r['date']>=today]
    events=read_json(DATA/'changes.json',[])
    dated=[]
    for d in dates:
        days=(date.fromisoformat(d['date'])-date.fromisoformat(today)).days
        dated.append(f'<article class="date-row"><time datetime="{e(d["date"])}">{e(date_text(d["date"]))}</time>'
                     f'<div><p class="agency">{e(d["program"])}</p><h3>{e(d["event"])}</h3>'
                     f'{link(d["source_url"],"Official source")} · <small>Captured {e(d["date_captured"])}</small>'
                     f'<p class="meta">{e(d.get("check") or d.get("evidence",""))}</p></div>'
                     f'<span class="days" data-due="{e(d["date"])}">{days} days</span></article>')
    changes=[change_html({**ev,'agency':lookup.get(ev['source'],{}).get('agency')}) for ev in events if ev['type']=='change']
    if not changes:
        changes.append(f'<p class="empty">Monitoring began {e(date_text(state["baseline"]))}. '
                       'No page or document changes have been recorded in this window.</p>')
    hdfc = [r for r in dates if r['program']=='HDFC']
    priority = ''.join(f'<p><strong>{e(date_text(r["date"]))}</strong><br>{e(r["event"])}</p>' for r in hdfc)
    for sid in ('hdfc-rules','hdfc-meetings'):
        if s:=lookup.get(sid):
            priority+=f'<p>{link(s["url"],s["name"])}</p>'
            if not health[sid].get('ok'):
                priority+='<p>Source check failed. See source health.</p>'
    grouped=defaultdict(list)
    for s in sources:
        h=health[s['id']]
        status='OK' if h.get('ok') else h.get('error','Unavailable')
        seen = datetime.fromisoformat(h['last_success']).astimezone(PACIFIC).strftime('%b %-d, %Y · %-I:%M %p %Z') if h.get('last_success') else 'No successful collection'
        snap=read_json(snap_path(s),{})
        qty=f'{len(snap["documents"])} document links' if 'documents' in snap else ''
        grouped[s['agency']].append(f'<tr><td>{link(s.get("public_url",s["url"]),s["name"])}<br><small>{e(s["notes"])}</small></td>'
                                    f'<td>{e(status)}</td><td>{e(seen)}<br><small>{e(qty)}</small></td></tr>')
    source_report = ['# Source status', '', f'Collection observed {stamp} (Pacific). Click a source for the official page.', '',
                     '| Agency | Source | Result | Last successful fetch (Pacific) |', '|---|---|---|---|']
    for s in sources:
        h=health[s['id']]
        result = 'OK' if h['ok'] else h.get('error','Unavailable').replace('|',' / ')
        name = s['name'].replace('|',' / ')
        source_report.append(f"| {s['agency']} | [{name}]({s.get('public_url',s['url'])}) | {result} | {h.get('last_success','None')} |")
    write(DATA/'source-status.md','\n'.join(source_report)+'\n')
    table=''.join(f'<details class="health-row"><summary><strong>{e(agency)}</strong> ({len(rows)})</summary>'
                  '<table><thead><tr><th>Source</th><th>Status</th><th>Last successful fetch (Pacific)</th></tr></thead>'
                  '<tbody>'+''.join(rows)+'</tbody></table></details>' for agency,rows in grouped.items())
    # Put failed sources in plain sight, including failures in collapsed groups.
    errors=[s for s in sources if not health[s['id']].get('ok')]
    if errors:
        table='<p class="empty">Needs attention: '+', '.join(link(s.get('public_url',s['url']),s['agency']+' · '+s['name']) for s in errors)+'</p>'+table
    land_sources=[s for s in sources if s.get('kind') in ('land_csv','land_map')]
    records={}
    statewide=''
    unlocated=0
    for s in land_sources:
        land_snapshot=read_json(snap_path(s),{})
        statewide=max(statewide,land_snapshot.get('latest_statewide',''))
        unlocated+=land_snapshot.get('unassigned',0)
        for row in land_snapshot.get('rows',[]):
            records[land_key(row)]=row
    rows = sorted((r for r in records.values() if r['county'] in conf['counties']),
                  key=lambda r:(r['notice_date'],r['case'],r['apn']),reverse=True)
    active = [r for r in rows if r['status'].casefold() == 'active']
    latest = active[0]['notice_date'] if active else ''
    land_source = land_sources[0] if land_sources else {}
    land_html=''.join(land_card(r,state['first_seen'].get(land_key(r),''),today,land_source,state.get('land_baseline')) for r in rows)
    noun = 'parcel' if len(active) == 1 else 'parcels'
    land_summary=(f'<p><span id="land-summary">{len(active):,} active {noun} across the monitored counties.</span> '
                  'NEW lasts 14 days from the first time Radar sees a parcel. For the initial import, only notices HCD issued '
                  'on the import date or in the preceding 14 days qualify. Check the response date and the agency notice.</p>')
    if unlocated:
        land_summary+=f'<p>{unlocated} statewide parcels could not be assigned a county.</p>'
    if any(not health[s['id']]['ok'] for s in land_sources):
        land_summary+='<p>HCD collection failed. Showing the most recent saved records.</p>'
    land_changes=[ev for ev in events if ev['type'] in ('land','land_update')]
    if land_changes:
        land_summary+='<details><summary>Recent land additions and revisions ('+str(len(land_changes))+')</summary><ul>'+''.join(
            '<li>'+e(ev['at'][:10])+' · '+link(ev['url'],ev['title'])+' · '+e(ev.get('added') or 'First observed')+'</li>' for ev in land_changes)+'</ul></details>'
    latest_line='Latest matching notice: '+date_text(latest) if latest else 'No matching dated notices'
    if statewide and statewide!=latest:
        latest_line+=' · Statewide: '+date_text(statewide)
    programs = sections(ROOT/'programs.yaml', sources, health, today)
    fields=dict(pbv=programs.get('pbv',''),funding=programs.get('funding',''),asof=e(datetime.fromisoformat(stamp).astimezone(PACIFIC).strftime('%b %-d, %Y · %-I:%M %p %Z')),
        coverage=f'{len(sources)} official sources',health_summary=f'{len(sources)-len(errors)} healthy · {len(errors)} need attention',
        freshness=f'<span data-asof="{e(today)}"></span>',changes=''.join(changes),land=land_html or '<p>No matching records.</p>',
        hdfc=priority,dates=''.join(dated) or '<p>No upcoming dates have been verified.</p>',health=table,
        latest_land=e(latest_line),statewide_notice=e(statewide),land_summary=land_summary,counties=''.join(f'<option>{e(c)}</option>' for c in sorted(conf['counties'])))
    dist=ROOT/'dist'; dist.mkdir(exist_ok=True)
    write(dist/'index.html',Template((ROOT/'web/index.tmpl').read_text()).substitute(fields))
    write(dist/'feed.xml',atom(events,conf['site_url'],stamp))
    for asset in ('app.js','style.css'):
        shutil.copyfile(ROOT/'web'/asset,dist/asset)
    return len(rows), statewide


if __name__ == '__main__':
    print('Local parcels, latest statewide notice:',*render())
