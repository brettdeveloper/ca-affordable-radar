"""Idempotent daily issue delivery with the ephemeral Actions token via GitHub CLI."""
import json
import os
import re
import subprocess
from collections import defaultdict
from tempfile import TemporaryDirectory
from pathlib import Path

from .extract import safe_url
from .state import DATA, config, read_json, signature


def gh(*args):
    return subprocess.run(['gh',*args],capture_output=True,text=True,check=True).stdout


def literal(value):
    # Do not ping GitHub users or turn publisher text into markup.
    return re.sub(r'([\\\[\]_*<>#\x60|])',r'\\\1',' '.join(str(value).split())).replace('@','@\u200b')


def mdlink(label,url):
    url = safe_url(url).replace('(','%28').replace(')','%29').replace(' ','%20')
    return f'[{literal(label)}]({url})' if url else literal(label)


def issue_body(day, events, url):
    token=signature(day,[e['id'] for e in events])
    marker=f'<!-- ca-affordable-radar {day} {token} -->'
    lines=[f'Official-source changes observed on {day} (Pacific).',mdlink('Full report and source health',url),'']
    for event in events:
        line='- '+mdlink(event['title'],event['url'])
        if event['type']!='change':
            line+=f" · {literal(event.get('county',''))} County · {literal(event.get('agency',''))} · issued {literal(event.get('notice_date') or 'date unavailable')}"
        lines.append(line)
        if event.get('added'):
            lines.append('  - Added: '+literal(event['added']))
        if event.get('removed'):
            lines.append('  - Removed: '+literal(event['removed']))
        lines.extend('  - '+mdlink(t,u) for u,t in event.get('new_docs',{}).items())
    body='\n'.join(lines)
    if len(body)>59500:
        body=body[:59000].rsplit('\n',1)[0]+'\n\nFurther entries and documents appear in the full report.'
    return body+'\n\n'+marker, marker


def deliver():
    repo=os.environ['GITHUB_REPOSITORY']
    events=read_json(DATA/'changes.json',[])
    if not events:
        print('No alertable changes.')
        return
    groups=defaultdict(list)
    for ev in events:
        groups[ev['at'][:10]].append(ev)
    # Read all pages, including closed alerts. Recovery after a lost response or
    # failed job can therefore reuse the same issue without search-index delay.
    result=json.loads(gh('api','--paginate','--slurp',f'repos/{repo}/issues?state=all&per_page=100&since={min(groups)}T00:00:00Z'))
    existing={i['title']:i for page in result for i in page if 'pull_request' not in i and
              i['user']['login']=='github-actions[bot]' and '<!-- ca-affordable-radar ' in (i.get('body') or '')}
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/'issue.md'
        for day,items in sorted(groups.items()):
            title=f'CA Affordable Housing Radar | {day}'
            body, marker=issue_body(day,items,config()['site_url'])
            old=existing.get(title)
            if old and marker in old['body']:
                continue
            path.write_text(body,encoding='utf-8')
            if old:
                print(gh('issue','edit',str(old['number']),'--repo',repo,'--body-file',str(path)).strip())
            else:
                print(gh('issue','create','--repo',repo,'--title',title,'--body-file',str(path)).strip())


if __name__=='__main__':
    deliver()
