"""Regression tests for the public HCD parcel view."""
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lxml import html

from radar import render, state


class LandViewTest(unittest.TestCase):
    def test_new_badges_on_baseline_and_later_imports(self):
        baseline = "2026-11-25"
        cases = [
            # First seen, HCD notice issued, viewing date, expected NEW.
            (baseline, "2026-11-10", baseline, False),
            (baseline, "2026-11-11", baseline, True),
            (baseline, baseline, baseline, True),
            (baseline, "2026-11-26", baseline, False),
            (baseline, "", baseline, False),
            (baseline, "2026-11-12", "2026-12-09", False),
            ("2026-11-26", "2024-01-01", "2026-12-09", True),
            ("2026-11-26", "", "2026-11-26", True),
            ("2026-11-26", "2024-01-01", "2026-12-10", False),
        ]
        for first, notice, today, expected in cases:
            with self.subTest(first=first, notice=notice, today=today):
                badge = render.land_badge(first, notice, baseline, today)
                if expected:
                    self.assertEqual(html.fromstring(badge).text_content(), "NEW")
                    self.assertEqual(html.fromstring(badge).get("data-first-seen"), first)
                else:
                    self.assertEqual(badge, "")

    def test_active_default_and_filtered_pagination(self):
        browser = shutil.which("google-chrome") or shutil.which("chromium")
        if not browser:
            self.skipTest("Chrome or Chromium is required for the browser test")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            shutil.copytree(state.ROOT / "web", root / "web")
            source = dict(id="land", kind="land_csv", name="Land", agency="HCD",
                          category="Land", notes="Test fixture", url="https://www.hcd.ca.gov/")
            state.json_out(root / "sources.yaml", [source])
            state.json_out(root / "config.yaml", dict(counties=["Marin", "Los Angeles"], site_url=source["url"]))
            state.json_out(data / "deadlines.yaml", [])
            state.json_out(data / "state.json", dict(as_of="2026-11-25T06:00:00-08:00",
                           baseline="2026-11-25", land_baseline="2026-11-25",
                           first_seen={}, health={"land": {"ok": True}}))
            rows = [dict(apn=str(n), case="SLA", agency="Agency", site=str(n), city="", acreage="", due_date="",
                         county="Marin" if n == 10 else "Los Angeles", status="Active" if n < 9 else "Archive",
                         notice_date="2026-11-12" if n < 9 else "2026-11-05") for n in range(11)]
            state.json_out(data / "snapshots/land.json", {"rows": rows})
            with patch.multiple(state, ROOT=root, DATA=data), patch.multiple(render, ROOT=root, DATA=data):
                render.render()

            index = root / "dist/index.html"
            page = index.read_text()
            default = html.fromstring(page)
            self.assertEqual(default.get_element_by_id("land-summary").text, "9 active parcels across the monitored counties.")
            self.assertEqual(len(default.xpath('//*[@id="parcels"]/article[not(@hidden)]')), 9)
            # Exercise the actual controls and deferred app.js on the rendered page.
            driver = """
            <pre id="observations"></pre><script>
            window.addEventListener("DOMContentLoaded", () => {
              const byId = id => document.getElementById(id);
              const observations = [];
              function observe() {
                const visible = [...document.querySelectorAll("#parcels article:not([hidden])")];
                observations.push([byId("availability").value, byId("land-summary").textContent,
                  byId("land-count").textContent, visible.map(p => p.dataset.status),
                  byId("land-prev").disabled, byId("land-next").disabled]);
              }
              function choose(id, value) {
                byId(id).value = value;
                byId(id).dispatchEvent(new Event("change"));
                observe();
              }
              observe();
              byId("land-next").click();
              observe();
              choose("availability", "Archive");
              choose("county", "Marin");
              choose("availability", "Active");
              choose("county", "");
              choose("availability", "");
              byId("observations").textContent = JSON.stringify(observations);
            });
            </script>"""
            index.write_text(page.replace("</body>", driver + "</body>"))
            result = subprocess.run([browser, "--headless", "--no-sandbox", "--disable-dev-shm-usage",
                                     "--user-data-dir=" + str(root / "profile"), "--dump-dom", index.as_uri()],
                                    capture_output=True, text=True, check=True, timeout=45)
            output = html.fromstring(result.stdout).get_element_by_id("observations").text
            self.assertEqual(json.loads(output), [
                ["Active", "9 active parcels across the monitored counties.", "Showing 1–8 of 9 records", ["Active"]*8, True, False],
                ["Active", "9 active parcels across the monitored counties.", "Showing 9–9 of 9 records", ["Active"], False, True],
                ["Archive", "2 archived parcels across the monitored counties.", "Showing 1–2 of 2 records", ["Archive"]*2, True, True],
                ["Archive", "1 archived parcel in Marin County.", "Showing 1–1 of 1 records", ["Archive"], True, True],
                ["Active", "0 active parcels in Marin County.", "No records match these filters.", [], True, True],
                ["Active", "9 active parcels across the monitored counties.", "Showing 1–8 of 9 records", ["Active"]*8, True, False],
                ["", "11 parcels across the monitored counties.", "Showing 1–8 of 11 records", ["Active"]*8, True, False],
            ])
