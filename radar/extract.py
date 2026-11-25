"""Normalized page text and published document inventory. No scripts execute."""
import hashlib
import io
import re
from collections import Counter
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from lxml import etree, html

from .net import MonitorError

DOC = re.compile(r'\.(?:pdf|xlsx?|docx?|xlsm|csv|rtf|pptx?|zip)(?:[/?#&;]|$)', re.I)
DOC_LABEL = re.compile(r'\b(?:PDF|DOCX?|XLSX?|XLSM|CSV|Word document|Excel workbook)\b', re.I)
TRACK = re.compile(r'^(?:utm_.*|fbclid|gclid|sessionid|phpsessid|jsessionid|token|_ga|cachebust|cachebuster)$', re.I)
BLOCK = re.compile(r'(?:^|\s)(?:breadcrumb[s]?|footer|cookie-banner|social-share|skip-links?|visually-hidden|screen-reader-text|mobile-menu|utility-nav|accessibility-menu)(?:$|\s)', re.I)
NOISE = re.compile(r'^(?:skip (?:to|over) .{0,70}|(?:page )?(?:visits|views|hits|visitors)\s*:?\s*[\d,]+|(?:page |website |site )?last (?:updated|modified)\s*:?\s*(?:\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec).{0,48}|copyright\s*©?.{0,90}|©\s*20\d{2}.{0,70})$', re.I)
RENDER_BLOCKS = {'address','article','aside','blockquote','br','dd','div','dl','dt','h1','h2','h3','h4','h5','h6','hr','li','main','ol','p','section','table','tr','ul'}


# Discard action links outright. Stripping a nonce can still leave a usable
# sign-in, subscription or participant URL, which has no place in a public log.
ACTION_HOSTS = ('neighborlysoftware.com', 'confirmsubscription.com', 'govdelivery.com',
                'list-manage.com', 'service-now.com', 'planetbids.com', 'biddingo.com',
                'teams.microsoft.com', 'surveymonkey.com', 'forms.office.com', 'zoom.us',
                'costar.com', 'loopnet.com', 'crexi.com')
ACTION_PATH = re.compile(r'(?:^|/)(?:oauth2?|openidoauth|authorize|sign[-_]?in|login|logout|subscribe|unsubscribe|passwordreset|resetpassword)(?:[./?_-]|$)', re.I)
PRIVATE_KEYS = re.compile(r'^(?:state|nonce|code|client_id|client_secret|access_token|refresh_token|id_token|token|sig|signature|session(?:_?id)?|phpsessid|jsessionid|x-amz-.+|x-goog-.+|samlrequest|samlresponse|relaystate)$', re.I)

def clean(s):
    return ' '.join(str(s or '').replace('\u200b', '').replace('\xad','').split())


def safe_url(link, base=''):
    link = urljoin(base, link.strip())
    try:
        p = urlsplit(link)
        if p.scheme.lower() not in ('http','https') or not p.hostname or p.username or p.password:
            return ''
        query = parse_qsl(p.query, keep_blank_values=True)
        if any(p.hostname == h or p.hostname.endswith('.'+h) for h in ACTION_HOSTS):
            return ''
        if ACTION_PATH.search(p.path) or any(PRIVATE_KEYS.match(k) for k,_ in query) or ';jsessionid=' in p.path.lower():
            return ''
        q = [(k,v) for k,v in query if not TRACK.match(k)]
        path = re.sub(r';jsessionid=[^/?;]+', '', p.path, flags=re.I)
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(q), ''))
    except ValueError:
        return ''


def blocks(node):
    pieces = []
    def walk(e):
        tag = e.tag
        if not isinstance(tag, str):
            return
        if tag in RENDER_BLOCKS:
            pieces.append('\n')
        if e.text:
            pieces.append(re.sub(r"\s+", " ", e.text))
        for child in e:
            walk(child)
            if child.tail:
                pieces.append(re.sub(r"\s+", " ", child.tail))
        if tag in ('td','th'):
            pieces.append(' | ')
        if tag in RENDER_BLOCKS:
            pieces.append('\n')
    walk(node)
    return [s for line in ''.join(pieces).splitlines() if (s:=clean(line).strip(' |')) and not NOISE.fullmatch(s)]


def snapshot_html(body, url, headers, source):
    # libxml's HTML4 default is Latin-1. Honor the publisher's HTTP or HTML charset.
    mime = headers.get('content-type','')
    charset = re.search(r'charset\s*=\s*["\x27]?([\w-]+)', mime, re.I)
    if not charset:
        charset = re.search(r'charset\s*=\s*["\x27]?([\w-]+)', body[:6000].decode('ascii','ignore'), re.I)
    try:
        parser = html.HTMLParser(encoding=charset.group(1) if charset else 'utf-8', no_network=True)
        root = html.document_fromstring(body, parser=parser)
    except (LookupError, ValueError, etree.ParserError) as exc:
        raise MonitorError("Unparseable HTML") from exc
    title = clean(' '.join(root.xpath('//title//text()')))
    if re.search(r'just a moment|access denied|attention required|403 forbidden|page not found|request rejected|human verification|checking your browser|security checkpoint|page unavailable', title,re.I):
        raise MonitorError("Server returned an error or challenge page")
    original = clean(root.text_content())
    if len(original)<7000 and re.search(r'verify (?:that )?you are human|requires javascript to (?:run|continue)|enable javascript and cookies to continue', original,re.I):
        raise MonitorError("JavaScript or human verification required")
    regions = root.xpath(source.get('xpath','//main | //*[@role="main"]'))
    if not regions:
        if source.get('xpath'):
            raise MonitorError("Expected content region is missing")
        regions = root.xpath('//*[@id="main-content" or @id="contentBody" or @id="maincontent" or @id="content" or @id="main"]')
    regions = [r for r in regions if len(clean(r.text_content())) >= min(65, source.get('min_chars',110))]
    container = max(regions, key=lambda e:len(clean(e.text_content()))) if regions else root
    for e in container.xpath('.//script|.//style|.//noscript|.//template|.//svg|.//nav|.//footer|.//form[@role="search"]|.//*[@role="navigation" or @role="contentinfo" or @role="banner"]|.//body/header'):
        e.drop_tree()
    for e in container.xpath('.//*[@class or @id]'):
        if BLOCK.search(e.get('class','')+' '+e.get('id','')):
            if e.getparent() is not None:
                e.drop_tree()
    lines = [re.sub(r'https?://[^\s<>]+',lambda m: safe_url(m.group()) or '[external portal]',line) for line in blocks(container)]
    if len(' '.join(lines)) < source.get('min_chars',110):
        raise MonitorError("Insufficient readable text; possible layout change")
    if source.get('require') and not re.search(source['require'],' '.join(lines),re.I):
        raise MonitorError("Expected source heading or vocabulary is missing")
    documents = {}
    linked = {}
    for a in container.xpath('.//a[@href]'):
        link = safe_url(a.get('href'),url)
        label = clean(a.text_content()) or clean(a.get('title')) or clean(a.get('aria-label'))
        hint = ' '.join([label, a.get('type',''), a.get('title',''), a.get('download','')])
        same_publisher = link and (urlsplit(link).hostname == urlsplit(url).hostname or
                                   (urlsplit(link).hostname or '').endswith(('.gov','.ca.us')))
        if same_publisher and label and (not source.get('track_links') or re.search(source['track_links'], link)):
            linked[link] = label
        if link and (DOC.search(link) or DOC_LABEL.search(hint) or a.get('download') is not None or re.search(r'/DocumentCenter/View/|/home/showpublisheddocument/|/pdf/|/LinkClick\.aspx|/files/[^/]+/download(?:[/?]|$)',link,re.I)):
            documents[link] = label or link.rsplit('/',1)[-1]
    return {'title':title,'lines':lines,'documents':dict(sorted(documents.items())), 'links':dict(sorted(linked.items()))}


def file_snapshot(content, source):
    # Direct official files may also be watched for revisions at an unchanged URL.
    kind = source['kind']
    if kind == 'pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = reader.pages
        if 'pdf_pages' in source:
            first, last = source['pdf_pages']
            if not 1 <= first <= last <= len(pages):
                raise MonitorError("Published PDF page range has changed")
            pages = pages[first - 1:last]
        lines = [clean(l) for page in pages for l in (page.extract_text() or '').splitlines() if clean(l)]
        if source.get('require') and not re.search(source['require'], ' '.join(lines), re.I):
            raise MonitorError("Expected text missing from published PDF")
    elif kind == 'xlsx':
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        lines = [f'{s.title} | ' + ' | '.join(clean(c) for c in row) for s in wb for row in s.values if any(c is not None for c in row)]
        wb.close()
    else:
        import zipfile
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            doc = etree.fromstring(z.read('word/document.xml'), parser=etree.XMLParser(resolve_entities=False,no_network=True))
        lines = [clean(''.join(p.xpath('.//*[local-name()="t"]/text()'))) for p in doc.xpath('//*[local-name()="p"]')]
    return {'title':source['name'], 'lines':lines, 'documents':{},'sha256':hashlib.sha256(content).hexdigest()}


def differences(old, new):
    a,b = old['lines'],new['lines']
    # Ignore re-sorting unchanged content. Preserve duplicate counts.
    def unmatched(lines, other):
        counts = Counter(other)
        result = []
        for line in lines:
            if counts[line]:
                counts[line] -= 1
            else:
                result.append(line)
        return result
    added, removed = unmatched(b,a), unmatched(a,b)
    plus = {k:v for k,v in new['documents'].items() if k not in old['documents']}
    minus = {k:v for k,v in old['documents'].items() if k not in new['documents']}
    before, after = old.get('links', {}), new.get('links', {})
    new_links = {u:v for u,v in after.items() if u not in before and u not in plus}
    lost_links = {u:v for u,v in before.items() if u not in after and u not in minus}
    if not (new_links or lost_links or added or removed or plus or minus or new.get('sha256') != old.get('sha256')):
        return None
    def excerpt(lines, other):
        if len(lines)==1 and len(other)==1 and len(lines[0])>320:
            matcher = SequenceMatcher(None, other[0].split(), lines[0].split(), autojunk=False)
            changed = [' '.join(lines[0].split()[max(0,i-5):j+6]) for tag,_,_,i,j in matcher.get_opcodes() if tag!='equal' and j>i]
            if changed:
                return clean(' … '.join(changed))[:500]
        return ' · '.join(lines)[:500]
    return {'added':excerpt(added,removed),'removed':excerpt(removed,added),'new_docs':plus,'removed_docs':minus,'new_links':new_links,'removed_links':lost_links}
