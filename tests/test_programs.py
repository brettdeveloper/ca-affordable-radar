"""Developer opportunities and source failure thresholds."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lxml import html

from radar.health import health_groups, threshold_failed
from radar.opportunities import evidence_matches, intake_offers, sections


class ProgramTests(unittest.TestCase):
    def test_pbv_round_needs_current_issuer_evidence(self):
        offer = {'until':'2026-12-03', 'evidence':{'guide':['up to 300 PBVs', 'Applications Due']},
                 'stop':['Round 33 is closed']}
        health = {'guide':{'ok':True}}
        snap = {'guide':{'lines':['Up to 300 PBVs.', 'Applications due December 3.']}}
        self.assertTrue(evidence_matches(offer, snap, health, '2026-12-03'))
        self.assertFalse(evidence_matches(offer, snap, health, '2026-12-04'))
        self.assertFalse(evidence_matches(offer, snap, {'guide':{'ok':False}}, '2026-11-25'))
        snap['guide']['lines'].append('Round 33 is closed.')
        self.assertFalse(evidence_matches(offer, snap, health, '2026-11-25'))

    def test_published_owner_intake_excludes_tenant_and_expired_notices(self):
        row = {'name':'Test Housing Authority', 'intake':['rfp']}
        snaps = {'rfp':{'lines':['PBV program | Open | Tenant waiting list',
                                 'We are now accepting proposals for up to 30 PBVs. Applications due December 4, 2026.',
                                 'Now accepting proposals for 40 PBVs. Applications due March 5, 2024.']}}
        result = intake_offers('pbv', row, snaps, {'rfp':{'ok':True}}, '2026-11-25')
        self.assertEqual([(r['until'],r['value']) for r in result], [('2026-12-04','up to 30 PBVs')])

    def test_pbv_section_groups_one_authority_with_multiple_sources(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'programs.yaml'
            path.write_text("pbv:\n- {county: Marin, name: Marin PHA, sources: [a, b]}\n")
            sources = [dict(id=k, name="Source "+k, url="https://example.gov/"+k) for k in ('a','b')]
            health = {k: {'ok':True,'last_change':v} for k,v in [('a','2026-11-20'),('b','2026-11-24')]}
            section = html.fromstring(sections(path,sources,health,'2026-11-25')['pbv'])
            self.assertIn('Marin (1)', section.xpath('string(summary)'))
            self.assertEqual(len(section.xpath('.//article')), 1)
            self.assertEqual(len(section.xpath('.//a')), 2)
            self.assertIn('No open solicitation shown',section.text_content())
            self.assertIn('Nov 24, 2026',section.text_content())

    def test_health_threshold_by_government_group(self):
        sources = [dict(id=str(i),category='Local funding' if i<80 else 'Funding') for i in range(100)]
        health = {s['id']:{'ok':True} for s in sources}
        for i in list(range(5))+list(range(80,86)):
            health[str(i)]['ok'] = False
        self.assertFalse(threshold_failed(health_groups(sources, health)))
        health['86']['ok'] = False
        self.assertTrue(threshold_failed(health_groups(sources, health)))
