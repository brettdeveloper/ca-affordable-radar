# CA Affordable Housing Radar

A morning brief for California affordable housing acquisitions. It tracks proposed and adopted rules, application and award lists, funding notices, dated milestones, and public surplus parcels. All collection and rendering run in Python on GitHub. [Open the dashboard](https://brettdeveloper.github.io/ca-affordable-radar/) · [Atom feed](https://brettdeveloper.github.io/ca-affordable-radar/feed.xml) · [Each source and its last result](data/source-status.md)

## Launch snapshot · November 25, 2026

The initial run produced usable snapshots for **61 of 63** watched sources. Two Santa Barbara County webpages returned a page shell. Their public Board funding records were readable. The complete row-by-row launch results are in the source report; later runs update that report, and Git retains earlier versions.

HCD's weekly file contained **3,130 statewide parcel rows**. The eight selected counties contained **894 distinct case/parcel combinations**, with **24 Active** and **870 Archive**. The latest issued notice statewide and in those counties was **November 12, 2026**, from the City of Los Angeles for **11381 West Chalon Road**, APN **4369007900**, **0.726 acres**, case **SLA0003183**. HCD listed **January 10, 2027** as the response date. The catalog reported a November 20 update. [HCD's weekly list and map](https://www.hcd.ca.gov/planning-and-research/public-lands/surplus-land/accessing-land) · [Dataset and publication timestamp](https://data.ca.gov/@california-department-of-housing-and-community-development/surplus-land-act-notices-of-availability-received)

HDFC listed **December 4** for its pipeline survey and **December 18** for presentation of regulations for adoption. Its application opening was described only as “Early 2027.” The calendar leaves that window undated. Draft 2027 CDLAC/CTCAC submission dates are identified as preliminary, including the rehabilitation-only third QRRP/4% round. [HDFC timeline](https://www.hdfc.ca.gov/regulations/) · [Dated entries and evidence](data/deadlines.yaml)

## Turn it on

1. Open the [repository's Pages settings](https://github.com/brettdeveloper/ca-affordable-radar/settings/pages). Under **Build and deployment → Source**, select **GitHub Actions**. The existing workflow handles deployment.
2. To publish immediately, open [Actions → Housing Radar](https://github.com/brettdeveloper/ca-affordable-radar/actions/workflows/radar.yml), choose **Run workflow**, select **main**, then **Run workflow**. The next scheduled run also publishes. Before Pages is enabled the collector still saves state and sends new alerts.
3. For email, open the repository's **Watch → Custom → Issues**, or select **All Activity**. Enable email delivery for watched repositories in [notification settings](https://github.com/settings/notifications). GitHub controls delivery. Creating an issue does not itself verify delivery to your inbox.

With standard public-repository settings, no personal access token or secret is required. Actions and Issues must be enabled; repository rules must allow the workflow to push its data commit to main. The workflow declares its own job permissions. Change organization or branch restrictions only if a run reports that they block it. [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) · [GitHub notifications](https://docs.github.com/en/subscriptions-and-notifications/get-started/configuring-notifications)

## Daily run

The workflow requests **6:00 a.m. America/Los_Angeles** with a timezone-aware cron; GitHub queues may delay the start. Manual runs and changes to code, source definitions, or the calendar also trigger it. The collector deduplicates by Pacific calendar date. A same-day rerun republishes saved data and can recover an undelivered issue without polling the same sources twice.

- **Changes.** Each healthy page gets a normalized text snapshot, a document-link inventory and relevant page links. The collector strips scripts, navigation, footer timestamps, trackers and action URLs. It compares content independent of order, reports excerpts added and removed, and lists new and removed documents, including links whose caption stayed the same. The website and Atom retain 90 Pacific calendar days. Git history preserves previous snapshots. First observations establish the baseline quietly.
- **Files.** PDF, Excel and Word links are inventoried on source pages. Directly registered PDF, XLSX and DOCX files additionally receive text and checksum comparison for replacements at the same URL. The HDFC draft, redline and notice, plus committee schedule PDFs, have direct watches. Other linked files are reported when their published links/labels change. An unregistered attachment replaced in place without any page change can be missed. Image-only PDFs have checksum coverage without OCR. Files and accounts reached only through an application portal are outside the collection.
- **Land.** The collector reads the complete public CSV export of the resource linked by HCD. The government catalog and source landing page are watched for moves. It reads `Date Notice Issued`, preserves APNs as text and uses HCD's case plus parcel identifier to distinguish parcels from later offerings. A missing APN falls back to site and coordinates. A single NOA can cover many parcels. No deal size is calculated by summing repeated acreage descriptions. The weekly source includes archived, expired and occasionally incomplete entries.
- **Counties.** The CSV omits county. The collector joins the reported site coordinates to a bundled, generalized California county-boundary reference, with exact incorporated-city names as a fallback. This uses the site's location, including land owned by a different county. The page reports any unassigned records. Boundary-adjacent sites and conflicting city/coordinate data warrant a parcel-level check. The reference includes its source URLs and preparation date. [California county boundaries](https://publish.data.ca.gov/dataset/california-county-boundaries-and-identifiers) · [California city boundaries](https://publish.data.ca.gov/dataset/california-city-boundaries-and-identifiers)
- **NEW.** The land view opens on HCD Active parcels. The status and county filters update the parcel total, latest matching notice and page count. NEW lasts 14 calendar days starting with first observation. For parcels first seen on the initial land import, the HCD notice must also have been issued on the import date or in the preceding 14 days. HCD's issued date and Active/Archive status remain visible. Only later arrivals and material updates enter issues and Atom. The launch CSV and public map agreed on the latest statewide notice. The map included an additional Hayward case, outside the eight counties. Its GIS robots endpoint returned HTTP 500, so the unattended feed uses the weekly CSV.
- **Dates.** The calendar shows published dates, source links, evidence, qualifications and capture dates. It distinguishes issuance, applications, awards, hearings and proposed adoption. Reviewed HDFC timeline rules can update a date when the publisher changes it or withdraw it when there is no longer an exact date. Other entries are curated. A change to a watched evidence source flags the date for review. Newly announced deadlines also surface as source changes; there is no automatic interpretation of every new NOFA. The calendar records San Mateo County's conflicting Winter NOFA projections.
- **Alerts.** Page changes, document changes and new or updated in-scope land records are grouped into one GitHub Issue per observation day. Daily issue identifiers prevent duplicates, including on replay. A failed delivery can be retried from the retained 90-day history. The Atom feed carries stable event IDs. A quiet baseline has no fabricated feed items or issue.
- **Health.** Every source has its last attempt, last successful check, and failure reason. A challenge page, missing content, a broken schema or robots refusal is a failure even after an HTTP 200. A severe content drop is quarantined until a second daily observation confirms it. Good snapshots survive a failed fetch. When **more than 30%** fail, a separate workflow job fails and a configured Pages deployment can still show the degraded health. If the entire workflow stops, the page displays a stale warning after two Pacific days.
- **Repository activity.** Each new collection day commits the actual fetch ledger and per-source health on main even on quiet news days. This supplies ongoing repository activity before GitHub's 60-day public-repository inactivity cutoff. It depends on successful state pushes. If the schedule is already disabled, re-enable **Housing Radar** in Actions and run it once. [Scheduling and inactivity](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) · [Timezone-aware schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule)

## Change what Radar watches

- Edit [sources.yaml](sources.yaml). Each item has a stable `id`, `name`, `agency`, `category`, HTTPS `url` and `notes`. Copy a similar entry, give it a new ID, and verify that the URL contains the public agency material and permits automated reading. An optional XPath selects the main region; `require` checks that expected content actually appears. The two annual program indexes discover new CDLAC and CTCAC award-page URLs by matching the government-published link and verifying the response before appending it to the registry. This also preserves the previous program year.
- Edit `counties` in [config.yaml](config.yaml) to change the land filter. The next daily CSV fetch imports the new county. The public snapshot retains parcels in the selected counties, statewide counts and the latest statewide date. Parcel links lead to agency materials or a case-filtered HCD CSV with the agency’s published contact. Staff contact lists are omitted from the public repository.
- Edit [data/deadlines.yaml](data/deadlines.yaml) to add a program, event, ISO date, official source URL, capture date and short supporting evidence. Qualify anything proposed, contingent or subject to earlier exhaustion. Keep an undated window in the source notes.
- The request client identifies the project in its user agent. It checks robots rules per origin, including redirect destinations, observes crawl delays, uses 12-second network timeouts and retries transient errors with exponential backoff up to three attempts. A completed daily request or terminal failure is not fetched again that day. It treats missing robots files (404/410) as no published rules and fails closed on other unavailable or unreadable policies. It never logs in. Santa Maria's official committee index uses one read-only JSON POST because that is how the city publishes its meeting calendar.

## Coverage limits at launch

| Jurisdiction | Automated coverage | Gap |
|---|---|---|
| San José | City WebGrants public posting table; the zero-row launch table had the expected headers. Santa Clara County OSH is monitored separately. | The Housing Department's Rolling RFP/NOFA page and its robots file returned HTTP 403. Some city materials require Biddingo registration. [City NOFA page](https://www.sanjoseca.gov/your-government/departments-offices/housing/developers/notice-of-funding-availability) |
| Santa Barbara County | County Board legislative records for NOFAs, PLHA and housing annual action plans. | The department and current-NOFA pages returned frontend shells. The underlying article service required authentication. Staff may announce a round before a Board filing. |
| Santa Maria | City-published Block Grants Advisory Committee index and FY 2027–28 NOFA agenda. | The city's general CDBG site and robots endpoint returned 403. Committee publication may lag staff notices. |
| San Diego | SDHC funding and announcements, City Bridge to Home and County HCDS funding. | SDHC directs applicants to a registration-only PlanetBids portal for full packages. |
| Statewide | HCD program and Super NOFA pages supplement the statewide NOFA calendar. HUD's separate MTSP page covers LIHTC/bond limits. | A portal's update date, a meeting agenda and a draft rule each have different implications. Use the adopted text, effective date and applicable round before underwriting. |

The site uses standard public GitHub-hosted Linux runners, GitHub Pages and their short-lived deployment artifact. All runtime dependencies are open-source. The repository supplies its own ephemeral GitHub token for authorized repository operations. No third-party accounts, paid services, API keys, LLM calls or ChatGPT subscription are required. [GitHub Actions free use](https://docs.github.com/en/billing/concepts/product-billing/github-actions#free-use-of-github-actions)

## Run locally

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python -m radar.collect
python -m radar.render
python -m http.server 8000 --directory dist
```

To preview the committed baseline without making network requests, run only the renderer and local server after installing dependencies. The deployment uploads only `dist/`, which contains the single HTML page, its local stylesheet and script, and the feed.

## Project-based vouchers

The owner/developer view groups housing authorities by county. An open tenant waiting list, board recommendation, past award, administrative-plan example or draft for public comment does not establish open developer intake. Each row links to the official material actually monitored. A coverage gap means the publisher’s owner materials could not be verified. “No open solicitation shown” describes the checked publications. An application portal can contain additional information that requires registration.

Edit the authority and source IDs in `programs.yaml` and the watched URLs in `sources.yaml`. Reviewed offers require the specified wording in healthy sources and expire after the published date. On designated intake pages, an explicit open developer invitation or open table row can also surface automatically. The parser uses dates and amounts attributable to the same entry and abstains on ambiguous dated text. New explicit application deadlines are appended to `data/deadlines.yaml`. Other changes go to the change list, issue and Atom feed for review. Last change starts with the first observed revision. A plan’s selected physical PDF pages and expected vocabulary are recorded in the source definition.

The Health job evaluates local government sources and state/federal sources separately. More than 30% failures in either group fails the run. Exactly 30% passes. A few inaccessible municipal sites cannot dilute a state outage. The collection job has a 24-minute ceiling on a standard free public Linux runner. GitHub controls queue and deployment time.

## Local funding

Expand a county to find local capital, preservation, HOME, CDBG, PLHA and related programs. A city funding announcement, a city application to the state, a public hearing, a capital award and a developer application are identified separately. Local funding displays the capital side of joint rounds. The voucher solicitation appears under its issuing PHA. A forthcoming month is shown as published; only exact dates enter the calendar. An issuer’s dated release with no public closing date can have a short open-status review window in `programs.yaml`. This is a verification limit, not an application deadline. Balance and eligibility qualifications appear beside rolling rounds.

### City coverage gaps checked November 25, 2026

The following cities have no verified standalone city funding watch. County and consortium rows may still cover opportunities within them.

| City | What was checked |
|---|---|
| Campbell | The city says it no longer administers CDBG and directs applicants to Santa Clara County. The county Urban County plan is watched. |
| Morgan Hill | Developer Resources covers inclusionary requirements. The Housing Successor annual report describes existing balances and loans. Neither offered a developer funding round. |
| San Carlos | Found the affordable housing program, linkage-fee rules, budgets and individual projects. No city application or round index was verified. |
| Belmont | The Housing Developer Resources host and the alternate council packet host returned HTTP 403 for robots.txt. |
| Scotts Valley | Found a Town Center development-partner RFP and housing-element policies. No city grant or loan round was identified. |
| Novato | The city housing and in-lieu fund host returned HTTP 403 for robots.txt. No readable city intake route was verified. The Marin County NOFA remains covered. |
| Lompoc | The city CDBG/Housing Division host returned HTTP 403 for robots.txt. News reports about a 2027–28 round could not establish an official deadline for the calendar. |
| West Hollywood | The project development page’s host returned HTTP 403 for robots.txt. The separate council host disallowed the trust-fund attachment. |
| Lancaster | The city CDBG index and action-plan documents share a host that returned HTTP 403 for robots.txt. |
| Carlsbad | The city and library document hosts returned HTTP 403 for robots.txt. The county-administered HOME consortium is covered. |
| Vista | The city’s developer funding host returned HTTP 403 for robots.txt. The county-administered HOME consortium is covered. |
| Encinitas | The city host returned HTTP 403 for robots.txt, and the separate council site disallowed the relevant attachment. The county-administered HOME consortium is covered. |

Several cities have partial coverage through their own council dockets, action plans or county-published joint offerings. Each affected program identifies that route. A prior award or plan can document a program without proving that applications are open today.
