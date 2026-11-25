import json
import unittest
from unittest.mock import Mock, patch

from lxml import html

from radar.alerts import issue_body
from radar.collect import fetch_source
from radar.health import health_groups, threshold_failed
from radar.industry import PORTFOLIO_HEADLINE, added_project_links, portfolio_snapshot, terms_digest
from radar.net import Response
from radar.render import atom
from radar.state import ROOT, catalog

URL = 'https://publisher.example/properties/'
TERMS = 'https://publisher.example/terms/'
STAMP = '2026-11-25T12:00:00-08:00'
POLICY = b'<main><h2>Last updated May 2</h2><p>Reviewed terms.</p><h3>Governing Law</h3></main>'
PORTFOLIO = b'''<main><p>A private project description</p><nav><a href="/about/">Navigation</a></nav>
<div class="et_pb_image"><a href="/river-park/?et_fb=1&amp;PageSpeed=off"><img alt="Private title"></a></div>
<div class="et_pb_image"><a href="/river-park"></a></div>
<div class="et_pb_image"><a href="/?page_id=42&amp;et_fb=1"></a></div>
<div class="et_pb_image"><a href="https://other.example/elsewhere/"></a></div>
<div class="et_pb_image"><a href="/login"></a></div>
<div class="et_pb_image"><a href="/?unreviewed=1"></a></div></main>'''


class IndustryTests(unittest.TestCase):
    def source(self):
        return dict(id='portfolio',name='Portfolio',url=URL,kind='industry_portfolio',category='Industry',
                    terms_url=TERMS,reviewed_terms_sha256=terms_digest(POLICY))

    def test_link_only_snapshot_deduplicates_without_copying_titles_or_text(self):
        snapshot = portfolio_snapshot(PORTFOLIO,URL)
        self.assertEqual(snapshot, {'project_links':['https://publisher.example/?page_id=42',
                                                    'https://publisher.example/river-park']})
        self.assertEqual(added_project_links(None,snapshot),[])
        self.assertEqual(added_project_links({'project_links':['https://publisher.example/river-park/']},snapshot),
                         ['https://publisher.example/?page_id=42'])
        self.assertNotIn('private',json.dumps(snapshot).lower())

    def test_changed_terms_stop_the_fetch_before_the_project_index(self):
        fetch=Mock()
        fetch.get.return_value=Response(200,{},POLICY.replace(b'Reviewed terms.', b'Updated terms.'),TERMS)
        with patch('radar.collect.read_json', return_value=None):
            health,old,new=fetch_source(self.source(),{},fetch,STAMP)
        fetch.get.assert_called_once_with(TERMS)
        self.assertFalse(health['ok'])
        self.assertIn('terms changed',health['error'])
        self.assertIsNone(new)

    def test_industry_has_no_effect_on_either_government_threshold(self):
        sources=[dict(id='state',category='Meetings'),dict(id='city',category='Local funding'),self.source()]
        health={'state':{'ok':True},'city':{'ok':True},'portfolio':{'ok':False}}
        groups=health_groups(sources,health)
        self.assertEqual(groups,{'state_federal':{'failed':0,'total':1},'local':{'failed':0,'total':1}})
        self.assertFalse(threshold_failed(groups))
        self.assertFalse(any('novoco.com' in s['url'] for s in catalog()))

    def test_industry_section_issue_and_atom_identify_the_nonofficial_source(self):
        page=html.fromstring((ROOT/'web/index.tmpl').read_text())
        section=page.get_element_by_id('industry')
        self.assertIn('Non-official',section.text_content())
        self.assertEqual(len(section.xpath('.//a[contains(@href,"novoco.com/terms-use")]')),1)
        event=dict(id='123',at=STAMP,source='portfolio',type='industry',title=PORTFOLIO_HEADLINE,url=URL+'example')
        body,_=issue_body(STAMP[:10],[event],'https://example.gov/')
        self.assertIn('Industry sources (non-official)',body)
        self.assertNotIn(' County',body)
        self.assertIn(b'Industry (non-official)',atom([event],'https://example.gov/',STAMP))
