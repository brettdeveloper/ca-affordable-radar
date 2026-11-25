"""Robots-aware, daily deduplicated GETs. Only configured source origins are followed."""
import json
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from threading import Lock
from time import monotonic, sleep, time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from protego import Protego

AGENT = "CAAffordableHousingRadar/1.0 (+https://github.com/brettdeveloper/ca-affordable-radar)"
TOKEN = "CAAffordableHousingRadar"
LIMIT = 40 * 1024 * 1024
REDIRECTS = {301, 302, 303, 307, 308}


class MonitorError(Exception):
    pass


class ManualRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes
    url: str
    observed_at: str = ''


def read_retry_after(value):
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time())
        except (TypeError, ValueError):
            return 0


class Fetcher:
    def __init__(self, sources, today, ledger):
        self.hosts = {urlsplit(s['url']).hostname for s in sources}
        for source in sources:
            self.hosts.update(source.get('redirect_hosts', []))
        self.posts = {s['url']:s['post_json'] for s in sources if s.get('post_json')}
        self.today = today
        self.ledger = ledger
        self.lock = Lock()
        self.futures = {}
        self.origin_locks = {}
        self.next_request = {}
        self.opener = build_opener(ManualRedirect())

    def once(self, key, work):
        with self.lock:
            first = key not in self.futures
            future = self.futures.setdefault(key, Future())
        if first:
            try:
                future.set_result(work())
            except Exception as exc:
                future.set_exception(exc)
        return future.result()

    def check_url(self, url):
        parts = urlsplit(url)
        if parts.scheme not in ('https', 'http') or parts.hostname not in self.hosts or parts.username or parts.password:
            raise MonitorError("Redirect outside the approved origins")

    def request(self, url, headers, delay, limit):
        host = urlsplit(url).netloc
        with self.lock:
            gate = self.origin_locks.setdefault(host, Lock())
        for attempt in range(3):
            with gate:
                sleep(max(0, self.next_request.get(host, 0) - monotonic()))
                self.next_request[host] = monotonic() + max(0.5, delay)
                payload = self.posts.get(url)
                if payload is not None:
                    headers = {**headers, 'Content-Type':'application/json; charset=utf-8'}
                req = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers={'User-Agent': AGENT, 'Accept-Encoding': 'identity', **headers})
                try:
                    with self.opener.open(req, timeout=12) as r:
                        body = r.read(limit + 1)
                        if len(body) > limit:
                            raise MonitorError(f"Response exceeds {limit:,} bytes")
                        return Response(r.status, dict(r.headers.items()), body, url)
                except HTTPError as exc:
                    with exc:
                        response = Response(exc.code, dict(exc.headers.items()), b'', url)
                        retry = read_retry_after(exc.headers.get('Retry-After'))
                        if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                            return response
                except (OSError, URLError) as exc:
                    if attempt == 2:
                        raise MonitorError(f"Network failure ({exc})") from exc
                    retry = 0
            if retry > 30:
                raise MonitorError("Server requested a later retry")
            sleep(max(retry, 2 ** attempt))
        raise MonitorError("Retry limit reached")

    def robots(self, origin):
        def get():
            saved = self.ledger.setdefault('robots', {}).get(origin, {})
            if saved.get('date') == self.today:
                if saved.get('error'):
                    raise MonitorError(saved['error'])
                return Protego.parse(saved['rules'])
            try:
                url = origin + '/robots.txt'
                for _ in range(6):
                    self.check_url(url)
                    r = self.once(('robots-url', url), lambda: self.request(url, {}, 0, 1024 * 1024))
                    h = {k.lower(): v for k, v in r.headers.items()}
                    if r.status in REDIRECTS and h.get('location'):
                        url = urljoin(url, h['location'])
                        continue
                    if r.status in (404, 410):
                        rules = ''
                    elif r.status == 200:
                        rules = r.body.decode('utf-8-sig', errors='replace')
                        if '<html' in rules[:1500].lower() or '<!doctype html' in rules[:1500].lower():
                            raise MonitorError("robots.txt returned an HTML page")
                    else:
                        raise MonitorError(f"robots.txt HTTP {r.status}")
                    self.ledger['robots'][origin] = {'date': self.today, 'rules': rules}
                    return Protego.parse(rules)
                raise MonitorError("robots.txt redirect limit")
            except Exception as exc:
                self.ledger['robots'][origin] = {'date': self.today, 'error': str(exc)}
                raise
        return self.once(('policy', origin), get)

    def get(self, url, headers=None):
        visited = set()
        for _ in range(7):
            self.check_url(url)
            if url in visited:
                raise MonitorError("Redirect loop")
            visited.add(url)
            p = urlsplit(url)
            policy = self.robots(f"{p.scheme}://{p.netloc}")
            if not policy.can_fetch(url, TOKEN):
                raise MonitorError("Access disallowed by robots.txt")
            delay = policy.crawl_delay(TOKEN) or 0
            rate = policy.request_rate(TOKEN)
            if rate and rate.requests:
                delay = max(delay, rate.seconds / rate.requests)
            if delay > 60:
                raise MonitorError("Robots crawl interval exceeds the run budget")
            def load():
                prior = self.ledger.setdefault('requests', {}).get(url)
                if prior and prior['date'] == self.today:
                    if prior['status'] in REDIRECTS:
                        return Response(prior['status'], {'location': prior['location']}, b'', url)
                    raise MonitorError("Already requested this Pacific day; next scheduled collection will retry")
                self.ledger['requests'][url] = {'date': self.today, 'status': 0}
                r = self.request(url, headers or {}, delay, LIMIT)
                fields = {k.lower(): v for k, v in r.headers.items()}
                self.ledger['requests'][url].update(status=r.status)
                if r.status in REDIRECTS:
                    self.ledger['requests'][url]['location'] = fields.get('location', '')
                return Response(r.status, fields, r.body, url, datetime.now(ZoneInfo('America/Los_Angeles')).isoformat(timespec='seconds'))
            r = self.once(('page', url), load)
            if r.status in REDIRECTS and r.headers.get('location'):
                url = urljoin(url, r.headers['location'])
                continue
            if r.status not in (200, 304):
                raise MonitorError(f"HTTP {r.status}")
            return r
        raise MonitorError("Page redirect limit")
