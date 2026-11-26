"""Link-only monitoring of the publisher's public project directory."""
import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from email.utils import parsedate_to_datetime

from lxml import etree, html

from .extract import safe_url
from .net import MonitorError

PORTFOLIO_HEADLINE = 'Kingdom Development added a project link'


def main_content(body):
    root = html.fromstring(body)
    regions = root.xpath('//main | //*[@id="main-content"]')
    if not regions:
        raise MonitorError('Publisher content region is missing')
    region = regions[0]
    for node in region.xpath('.//script | .//style | .//nav | .//footer | .//noscript | .//template'):
        node.drop_tree()
    return region


def terms_digest(body):
    region = main_content(body)
    words = unicodedata.normalize('NFKC', ' '.join(region.itertext())).casefold()
    text = ''.join(re.findall(r'[a-z0-9]+', words))
    start = text.find('lastupdated')
    if start < 0 or 'governinglaw' not in text[start:]:
        raise MonitorError('Publisher terms could not be verified')
    # Some layouts place the footer's link columns inside the main region.
    terms = text[start:].partition('helpfullinks')[0]
    return hashlib.sha256(terms.encode('ascii')).hexdigest()


def verify_terms(source, fetch):
    result = fetch.get(source['terms_url'])
    if result.status != 200 or terms_digest(result.body) != source['reviewed_terms_sha256']:
        raise MonitorError('Publisher terms changed or could not be verified; portfolio check paused')


def project_urls(hrefs, origin):
    projects = {}
    for href in hrefs:
        url = safe_url(href, origin)
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.netloc != urlsplit(origin).netloc:
            continue
        # The publisher includes Divi visual-editor switches on some public card links.
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if k.casefold() not in ('et_fb', 'pagespeed')]
        if query:
            if not (parts.path == '/' and len(query) == 1 and query[0][0] == 'page_id' and query[0][1].isdigit()):
                continue
        elif (not re.fullmatch(r'/[a-z0-9][a-z0-9-]*/?', parts.path, re.I)
              or parts.path.rstrip('/') == urlsplit(origin).path.rstrip('/')):
            continue
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
        key = url.rstrip('/')
        projects[key] = min(url, projects.get(key, url))
    return sorted(projects.values())


def portfolio_snapshot(body, url):
    main = main_content(body)
    # Project cards link their images. Ignore navigation, descriptions, image data and titles.
    hrefs = main.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," et_pb_image ")]/a[@href]/@href')
    projects = project_urls(hrefs, url)
    if not projects:
        raise MonitorError('No public project-card links found')
    return {'project_links': projects}


def added_project_links(old, new):
    if not old:
        return []
    prior = {u.rstrip('/') for u in old['project_links']}
    return [u for u in new['project_links'] if u.rstrip('/') not in prior]


def publication_snapshot(body, source):
    """Read only syndication metadata, keeping the newest items by publication date."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    channel = etree.fromstring(body, parser).find('channel')
    if channel is None or channel.findtext('title', '').strip().casefold() != source['feed_title'].casefold():
        raise MonitorError('Unexpected RSS channel')
    entries = {}
    for item in channel.findall('item'):
        url = safe_url(item.findtext('link', ''), source['url'])
        parts = urlsplit(url)
        title = ' '.join(item.findtext('title', '').split())
        if parts.scheme != 'https' or parts.netloc != urlsplit(source['url']).netloc or not title:
            continue
        try:
            published = parsedate_to_datetime(item.findtext('pubDate', '')).date().isoformat()
        except (ValueError, TypeError, OverflowError):
            continue
        entries[url] = {'url': url, 'title': title, 'published': published}
    if not entries:
        raise MonitorError('RSS feed contains no dated publisher links')
    recent = sorted(entries.values(), key=lambda item: (item['published'], item['url']), reverse=True)
    return {'publications': recent[:50]}
