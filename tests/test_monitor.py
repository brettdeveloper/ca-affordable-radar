import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from radar import alerts, collect, extract, net, render, state

URL='https://agency.ca.gov/finance'
SOURCE={'id':'housing','name':'Funding','agency':'Agency','url':URL,'min_chars':30}
TODAY='2026-11-25'


def page(text, suffix='', footer='1'):
    return f'<html><head><title>Finance</title></head><body class="site-footer-layout"><nav><main><h1>Funding notices</h1><p>{text}</p>{suffix}</main></nav><footer>Updated {footer}</footer></body></html>'.encode()


def snap(text, suffix='', footer='1'):
    return extract.snapshot_html(page(text,suffix,footer),URL,{},SOURCE)


class MonitorTests(unittest.TestCase):
    def test_document_link_and_readable_diff_without_tracking_noise(self):
        before=snap('Applications open November 1.', '<a href="/a.pdf?utm_source=mail">Instructions</a>')
        stable=snap('Applications open  \n November 1.', '<a href="/a.pdf?utm_source=text">Instructions</a>','2')
        self.assertIsNone(extract.differences(before,stable))
        after=snap('Applications open November 15.','<a href="/v2.xlsx">Scores</a>')
        diff=extract.differences(before,after)
        self.assertIn('November 15',diff['added'])
        self.assertIn('November 1',diff['removed'])
        self.assertEqual(list(diff['new_docs']),['https://agency.ca.gov/v2.xlsx'])

    def test_action_and_tracking_links_do_not_enter_public_snapshots(self):
        for u in ('https://confirmsubscription.com/h/example','https://login.neighborlysoftware.com/authorize',
                  'https://agency.ca.gov/download?state=opaque','https://agency.ca.gov/a.pdf?X-Amz-Signature=example'):
            self.assertEqual(extract.safe_url(u),'')
        self.assertEqual(extract.safe_url('https://agency.ca.gov/a.pdf?utm_source=mail'),'https://agency.ca.gov/a.pdf')

    def test_same_caption_changed_ordinary_link(self):
        before=snap('Published award applications.', '<a href="/2026">Current year</a>')
        after=snap('Published award applications.', '<a href="/2027">Current year</a>')
        self.assertIn('https://agency.ca.gov/2027', extract.differences(before,after)['new_links'])

    def test_challenge_and_structure_drop_preserve_baseline(self):
        with self.assertRaises(net.MonitorError):
            extract.snapshot_html(b'<title>Access denied</title>',URL,{},SOURCE)
        old={'lines':['data '*300], 'documents':{}}
        new={'lines':['short'], 'documents':{}}
        with self.assertRaises(net.MonitorError) as error:
            collect.check_structure(old,new,{},TODAY)
        h={'candidate':error.exception.candidate,'attempt_day':TODAY}
        with self.assertRaises(net.MonitorError):
            collect.check_structure(old,new,h,TODAY)
        collect.check_structure(old,new,h,'2026-11-26')

    def test_fetcher_deduplicates_and_checks_redirect_targets(self):
        f=net.Fetcher([SOURCE],TODAY,{})
        def response(url,*_):
            if url.endswith('robots.txt'):
                return net.Response(200,{},b'User-agent: *\nDisallow: /private\n',url)
            return net.Response(302,{'location':'/private'},b'',url)
        with patch.object(f,'request',side_effect=response) as requests:
            for _ in range(2):
                with self.assertRaisesRegex(net.MonitorError,'disallowed'):
                    f.get(URL)
            self.assertEqual(requests.call_count,2)
            self.assertFalse(any(c.args[0].endswith('/private') for c in requests.call_args_list))

    def test_rerun_uses_stored_pacific_day_and_robots_denial(self):
        f=net.Fetcher([SOURCE],TODAY,{'robots':{'https://agency.ca.gov':{'date':TODAY,'error':'robots.txt HTTP 503'}}})
        with patch.object(f,'request') as get:
            with self.assertRaisesRegex(net.MonitorError,'503'):
                f.get(URL)
            get.assert_not_called()
        with patch('radar.collect.read_json') as read:
            self.assertIsNone(collect.fetch_source(SOURCE,{'url':URL,'attempt_day':TODAY},None,TODAY+'T09:00:00-08:00'))
            read.assert_not_called()

    def test_feed_and_issue_markers_stable_and_escaped(self):
        ev={'id':'x','type':'change','at':'2026-11-25T06:00:00-08:00','url':URL,'title':'A < B & C',
            'added':'@name changed a date','new_docs':{URL+'/agenda.pdf':'Agenda'}}
        feed=ElementTree.fromstring(render.atom([ev],'https://example.org/',ev['at']))
        self.assertEqual(len(feed.findall('{http://www.w3.org/2005/Atom}entry')),1)
        body,marker=alerts.issue_body(TODAY,[ev],'https://example.org/')
        self.assertIn(marker,body)
        self.assertIn('agenda.pdf',body)
        self.assertNotIn('@name',body)

    def test_dated_hdfc_event_withdrawn_when_timeline_becomes_a_window(self):
        d=[{'program':'HDFC','event':'Adoption meeting','date':TODAY,'date_captured':TODAY,
            'source_url':URL,'anchor':'^Presentation$','section':'Timeline','until':'Resources'}]
        h={'health':{'housing':{'ok':True,'last_success':TODAY,'last_change':TODAY}}}
        import yaml
        with tempfile.TemporaryDirectory() as tmp, patch.object(state,'DATA',Path(tmp)):
            (Path(tmp)/'deadlines.yaml').write_text(yaml.safe_dump(d))
            data={'lines':['Timeline','Presentation','December 18, 2026','Resources']}
            with patch.object(state,'read_json',return_value=data):
                self.assertEqual(state.calendar([SOURCE],h)[0]['date'],'2026-12-18')
                data['lines'][2]='Early 2027'
                self.assertEqual(state.calendar([SOURCE],h),[])


if __name__=='__main__':
    unittest.main()
