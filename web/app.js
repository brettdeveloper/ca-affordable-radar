"use strict";

(function () {
  // County filters and paging work directly on the pre-rendered public records.
  const parcels = Array.from(document.querySelectorAll("#parcels .parcel"));
  const county = document.getElementById("county");
  if (parcels.length && county) {
    const status = document.getElementById("availability");
    const summary = document.getElementById("land-summary");
    const latest = document.getElementById("land-latest");
    const dateFormat = new Intl.DateTimeFormat("en-US", {month: "short", day: "numeric", year: "numeric", timeZone: "UTC"});
    const formatDay = iso => dateFormat.format(new Date(iso + "T00:00:00Z"));
    const pageSize = 8;
    const controls = document.getElementById("land-pages");
    const previous = document.getElementById("land-prev");
    const next = document.getElementById("land-next");
    const count = document.getElementById("land-count");
    let page = 0;

    function update() {
      const matches = parcels.filter(parcel => (!county.value || parcel.dataset.county === county.value) && (!status.value || parcel.dataset.status.toLowerCase() === status.value.toLowerCase()));
      const statusText = {"Active": "active ", "Archive": "archived ", "": ""}[status.value];
      const noun = matches.length === 1 ? "parcel" : "parcels";
      const place = county.value ? "in " + county.value + " County" : "across the monitored counties";
      summary.textContent = matches.length.toLocaleString() + " " + statusText + noun + " " + place + ".";
      // The renderer orders cards by notice date, newest first.
      const notice = matches[0]?.dataset.noticeDate;
      latest.textContent = notice ? "Latest matching notice: " + formatDay(notice) : "No matching dated notices";
      if (latest.dataset.statewide && latest.dataset.statewide !== notice) {
        latest.textContent += " · Statewide: " + formatDay(latest.dataset.statewide);
      }
      const start = page * pageSize;
      const shown = new Set(matches.slice(start, start + pageSize));
      for (const parcel of parcels) parcel.hidden = !shown.has(parcel);
      count.textContent = matches.length
        ? "Showing " + (start + 1) + "–" + Math.min(start + pageSize, matches.length) + " of " + matches.length.toLocaleString() + " records"
        : "No records match these filters.";
      previous.disabled = page === 0;
      next.disabled = start + pageSize >= matches.length;
    }

    for (const select of [county, status]) select.addEventListener("change", () => {
      page = 0;
      update();
    });
    for (const [button, step] of [[previous, -1], [next, 1]]) {
      button.addEventListener("click", () => {
        page += step;
        update();
        // Put readers at the first result of the new page on narrow screens.
        const first = document.querySelector("#parcels .parcel:not([hidden])");
        if (first && first.getBoundingClientRect().top < 0) {
          first.tabIndex = -1;
          first.focus({preventScroll: true});
          first.scrollIntoView({block: "start"});
        }
      });
    }
    county.closest(".county-control").hidden = false;
    controls.hidden = false;
    update();
  }

  // Compare Pacific calendar dates. UTC midnight arithmetic avoids DST-hour drift.
  function ordinal(iso) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(iso || "")) return NaN;
    return Date.parse(iso + "T00:00:00Z") / 86400000;
  }
  const pacific = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit"
  }).formatToParts(new Date());
  const today = Object.fromEntries(pacific.map(part => [part.type, part.value]));
  const now = ordinal(today.year + "-" + today.month + "-" + today.day);

  for (const badge of document.querySelectorAll("[data-first-seen]")) {
    const age = now - ordinal(badge.dataset.firstSeen);
    badge.hidden = !Number.isFinite(age) || age < 0 || age >= 14;
  }
  const dueDates = document.querySelectorAll("[data-due]");
  let upcoming = 0;
  for (const label of dueDates) {
    const days = ordinal(label.dataset.due) - now;
    if (!Number.isFinite(days)) continue;
    const row = label.closest(".date-row");
    if (row && days < 0) {
      row.hidden = true;
    } else {
      upcoming++;
      if (days >= 0) label.textContent = days === 0 ? "Today" : days === 1 ? "Tomorrow" : days + " days";
    }
  }
  if (dueDates.length && !upcoming) document.getElementById("no-upcoming").hidden = false;

  const stamp = document.querySelector("[data-asof]");
  const age = stamp ? now - ordinal(stamp.dataset.asof) : NaN;
  if (age >= 2) {
    const warning = document.getElementById("stale-warning");
    warning.textContent = "The last collection was " + age + " days ago. Check the official source for newer information.";
    warning.hidden = false;
  }
}());
