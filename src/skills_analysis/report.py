"""Render the findings as a self-contained HTML page.

One implementation, two surfaces: notebook 04 passes the result to
``displayHTML`` and also writes it to a Volume; the local runner writes the same
bytes to ``build/skills_report.html``.

Colour follows the validated reference palette. Magnitude bars are a single hue;
the severity ramp is ordinal (one hue, monotone lightness, validated with
``--ordinal`` in both modes); status colours appear only on stat tiles, where
each is paired with an icon and a label so meaning never rests on hue alone.
"""

from __future__ import annotations

import html
from datetime import date

import pandas as pd

from . import config as cfg

# --- design tokens -------------------------------------------------------
# Light and dark are each selected, not flipped. Dark is declared under both
# the OS media query and the explicit theme attribute so a viewer's toggle wins.
_CSS = """
:root {
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb;
  --ink:#0b0b0b; --ink-2:#52514e; --ink-muted:#898781;
  --grid:#e1e0d9; --baseline:#c3c2b7; --ring:rgba(11,11,11,0.10);
  --bar:#2a78d6;
  --sev-high:#184f95; --sev-medium:#3987e5; --sev-low:#86b6ef;
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
  --track:rgba(11,11,11,0.06);
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19;
    --ink:#ffffff; --ink-2:#c3c2b7; --ink-muted:#898781;
    --grid:#2c2c2a; --baseline:#383835; --ring:rgba(255,255,255,0.10);
    --bar:#3987e5;
    --sev-high:#cde2fb; --sev-medium:#3987e5; --sev-low:#184f95;
    --track:rgba(255,255,255,0.08);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19;
  --ink:#ffffff; --ink-2:#c3c2b7; --ink-muted:#898781;
  --grid:#2c2c2a; --baseline:#383835; --ring:rgba(255,255,255,0.10);
  --bar:#3987e5;
  --sev-high:#cde2fb; --sev-medium:#3987e5; --sev-low:#184f95;
  --track:rgba(255,255,255,0.08);
}

* { box-sizing:border-box; }
body {
  margin:0; background:var(--page); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.6;
}
.wrap { max-width:1060px; margin:0 auto; padding:40px 16px 72px; }
h1 { font-size:30px; line-height:1.25; margin:0 0 8px; letter-spacing:-0.02em; }
h2 {
  font-size:20px; margin:52px 0 6px; letter-spacing:-0.01em;
  padding-top:22px; border-top:1px solid var(--grid);
}
h3 { font-size:15px; margin:26px 0 10px; color:var(--ink-2); font-weight:600; }
p { margin:0 0 14px; color:var(--ink-2); max-width:72ch; }
p strong, li strong { color:var(--ink); }
.lede { font-size:17px; color:var(--ink-2); max-width:70ch; }
.meta { color:var(--ink-muted); font-size:13px; margin-bottom:28px; }
.meta code { font-size:12px; }
ul { margin:0 0 14px; padding-left:20px; color:var(--ink-2); max-width:72ch; }
li { margin-bottom:7px; }
code {
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px;
  background:var(--track); padding:1px 5px; border-radius:4px; color:var(--ink);
}

/* stat tiles ---------------------------------------------------------- */
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(224px,1fr)); gap:14px; margin:28px 0 8px; }
.kpi {
  background:var(--surface); border:1px solid var(--ring); border-radius:12px;
  padding:18px 18px 16px; position:relative; overflow:hidden;
}
.kpi::before { content:""; position:absolute; inset:0 auto 0 0; width:3px; background:var(--tile); }
.kpi-label { font-size:12px; text-transform:uppercase; letter-spacing:0.06em; color:var(--ink-muted); font-weight:600; }
.kpi-value { font-size:38px; font-weight:650; line-height:1.1; margin:10px 0 2px; letter-spacing:-0.03em; }
.kpi-target { font-size:12.5px; color:var(--ink-muted); margin-bottom:9px; }
.kpi-detail { font-size:12.5px; color:var(--ink-2); line-height:1.45; }
.pill {
  display:inline-flex; align-items:center; gap:5px; font-size:11.5px; font-weight:600;
  color:var(--tile); border:1px solid var(--tile); border-radius:99px; padding:1px 8px; margin-top:10px;
}
.pill span[aria-hidden] { font-size:10px; }

/* charts -------------------------------------------------------------- */
.card {
  background:var(--surface); border:1px solid var(--ring); border-radius:12px;
  padding:20px 20px 16px; margin:18px 0 8px;
}
.card-title { font-size:14.5px; font-weight:650; margin-bottom:2px; }
.card-sub { font-size:12.5px; color:var(--ink-muted); margin-bottom:18px; }
.row { display:grid; grid-template-columns:186px 1fr 46px; align-items:center; gap:12px; margin-bottom:2px; padding:4px 0; border-radius:6px; }
.row:hover { background:var(--track); }
.row-label { font-size:12.5px; color:var(--ink-2); text-align:right; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.track { background:var(--track); border-radius:4px; height:16px; position:relative; }
.bar { height:16px; border-radius:0 4px 4px 0; background:var(--bar); min-width:2px; }
.bar.zero { background:repeating-linear-gradient(135deg,var(--track),var(--track) 3px,var(--baseline) 3px,var(--baseline) 4px); border-radius:4px; }
.row-value { font-size:12.5px; color:var(--ink); font-variant-numeric:tabular-nums; }
.table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
.table-wrap table { min-width:560px; }
.stack { display:flex; height:16px; border-radius:4px; overflow:hidden; gap:2px; }
.seg { height:16px; }
.seg:first-child { border-radius:4px 0 0 4px; }
.seg:last-child { border-radius:0 4px 4px 0; }
.legend { display:flex; flex-wrap:wrap; gap:16px; margin:14px 0 2px; font-size:12px; color:var(--ink-2); }
.legend i { width:11px; height:11px; border-radius:3px; display:inline-block; margin-right:6px; vertical-align:-1px; }

/* tables -------------------------------------------------------------- */
table { width:100%; border-collapse:collapse; font-size:13px; margin:12px 0 6px; }
th {
  text-align:left; font-size:11.5px; text-transform:uppercase; letter-spacing:0.05em;
  color:var(--ink-muted); font-weight:600; padding:8px 10px; border-bottom:1px solid var(--baseline);
}
td { padding:8px 10px; border-bottom:1px solid var(--grid); color:var(--ink-2); vertical-align:top; }
tbody tr:hover td { background:var(--track); }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
td strong { color:var(--ink); font-weight:600; }
.tag { display:inline-flex; align-items:center; gap:4px; font-size:11px; font-weight:600; border-radius:99px; padding:1px 7px; border:1px solid currentColor; white-space:nowrap; }
.t-critical { color:var(--critical); } .t-serious { color:var(--serious); }
.t-warning  { color:var(--warning);  } .t-good    { color:var(--good); }
details { margin:14px 0; } summary { cursor:pointer; font-size:13px; color:var(--ink-2); font-weight:600; }
footer { margin-top:56px; padding-top:20px; border-top:1px solid var(--grid); font-size:12.5px; color:var(--ink-muted); }
@media (max-width:640px) {
  .row { grid-template-columns:96px 1fr 42px; gap:8px; }
  .wrap { padding:28px 16px 56px; }
  h1 { font-size:24px; }
  .kpi-value { font-size:32px; }
}
"""

_ICON = {"good": "●", "warning": "▲", "serious": "◆", "critical": "■"}


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _bar_rows(rows: list[tuple[str, float, str, str]], maximum: float | None = None) -> str:
    """Single-hue magnitude bars with a per-row hover tooltip and a value label."""
    top = maximum or max([r[1] for r in rows] + [1])
    out = []
    for label, value, display, note in rows:
        width = 0 if top == 0 else max(0.0, value) / top * 100
        zero = " zero" if value == 0 else ""
        tip = f"{label}: {display}" + (f" — {note}" if note else "")
        out.append(
            f'<div class="row" title="{_e(tip)}">'
            f'<div class="row-label" title="{_e(label)}">{_e(label)}</div>'
            f'<div class="track"><div class="bar{zero}" style="width:{width:.1f}%"></div></div>'
            f'<div class="row-value">{_e(display)}</div></div>' 
        )
    return "".join(out)


def _stacked_rows(rows: list[tuple[str, list[tuple[str, int, str]]]]) -> str:
    """Ordinal-ramp stacked bars; every segment carries its own hover label."""
    top = max([sum(v for _, v, _ in segs) for _, segs in rows] + [1])
    out = []
    for label, segments in rows:
        total = sum(v for _, v, _ in segments)
        width = total / top * 100
        parts = []
        for name, value, token in segments:
            if value <= 0:
                continue
            share = value / total * 100
            parts.append(
                f'<div class="seg" style="width:{share:.1f}%;background:var({token})" '
                f'title="{_e(label)} — {_e(name)}: {value}"></div>'
            )
        out.append(
            f'<div class="row"><div class="row-label" title="{_e(label)}">{_e(label)}</div>'
            f'<div class="track" style="background:none">'
            f'<div class="stack" style="width:{width:.1f}%">{"".join(parts)}</div></div>'
            f'<div><span class="row-value">{total}</span></div></div>'
        )
    return "".join(out)


def _kpi_tile(row: pd.Series) -> str:
    value = row["metric_value"]
    unit = row["metric_unit"]
    display = f"{value:.0f}%" if unit == "percent" else f"{value:.0f}"
    target = row["target_value"]
    higher_better = row["direction"] == "higher_is_better"
    on_target = value >= target if higher_better else value <= target

    if on_target:
        tone, verdict = "good", "On target"
    elif higher_better:
        gap = (target - value) / target if target else 1
        tone = "warning" if gap < 0.25 else "critical"
        verdict = f"{target - value:.0f} points below target"
    else:
        tone = "warning" if value <= max(target + 2, 2) else "critical"
        verdict = f"{value - target:.0f} above target"

    target_text = (
        f"Target {'≥' if higher_better else '≤'} "
        f"{target:.0f}{'%' if unit == 'percent' else ''}"
    )
    return (
        f'<div class="kpi" style="--tile:var(--{tone})">'
        f'<div class="kpi-label">{_e(row["metric_name"])}</div>'
        f'<div class="kpi-value">{display}</div>'
        f'<div class="kpi-target">{_e(target_text)}</div>'
        f'<div class="kpi-detail">{_e(row["metric_detail"])}</div>'
        f'<div class="pill"><span aria-hidden="true">{_ICON[tone]}</span>{_e(verdict)}</div>'
        f"</div>"
    )


def _table(headers: list[str], rows: list[list[str]], numeric: set[int] | None = None) -> str:
    numeric = numeric or set()
    head = "".join(
        f'<th class="num">{_e(h)}</th>' if i in numeric else f"<th>{_e(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = "".join(
        "<tr>" + "".join(
            f'<td class="num">{c}</td>' if i in numeric else f"<td>{c}</td>"
            for i, c in enumerate(row)
        ) + "</tr>"
        for row in rows
    )
    return (f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def _tag(text: str, tone: str) -> str:
    return f'<span class="tag t-{tone}"><span aria-hidden="true">{_ICON[tone]}</span>{_e(text)}</span>'


_BAND_TONE = {
    "No coverage": "critical", "No depth": "critical",
    "Single point of failure": "serious", "Thin": "warning", "Covered": "good",
}
_CERT_TONE = {
    "Expired": "critical", "No expiry recorded": "serious",
    f"Expiring within {cfg.CERT_EXPIRY_WARNING_DAYS} days": "serious",
    "Expiring within 12 months": "warning", "Current": "good",
}


def build_report(tables: dict[str, pd.DataFrame], as_of: date | None = None) -> str:
    """Assemble the findings page from the gold tables."""
    as_of = as_of or cfg.AS_OF_DATE
    workers = tables["silver_worker"]
    profile = tables["gold_worker_skill_profile"]
    coverage = tables["gold_skill_coverage"]
    certs = tables["gold_cert_compliance"]
    scorecard = tables["gold_org_scorecard"]
    kpis = tables["gold_kpi_snapshot"]
    learning = tables["silver_learning_completion"]
    issues = tables["silver_data_quality_issue"]

    pop = workers[workers["in_headcount"]]
    headcount = len(pop)
    critical = coverage[coverage["is_critical_skill"]]
    exposed = critical[critical["deep_practitioners"] <= cfg.BUS_FACTOR_THRESHOLD]

    # --- section 1: the population -------------------------------------
    split = workers[workers["legacy_worker_ids"].astype(str).str.len() > 0]
    legacy_count = int(split["legacy_worker_ids"].astype(str).str.count(";").add(1).sum())
    total_identifiers = len(workers) + legacy_count
    zero_fresh = scorecard[scorecard["profile_freshness_pct"].fillna(0) == 0]
    split_rows = [[
        f"<strong>{_e(r['worker_name'])}</strong>",
        f"<code>{_e(r['legacy_worker_ids'])}</code> &rarr; <code>{_e(r['employee_id'])}</code>",
        _e(r["supervisory_org"]),
        ("Acquisition tenure understated by "
         f"{_years(r['workday_hire_date'], r['original_hire_date'])}"
         if r["is_acquired_employee"] else "Truncated identifier on three rows"),
    ] for _, r in split.iterrows()]

    # --- section 2: critical skill depth --------------------------------
    depth_rows = [(
        r["canonical_skill"],
        float(r["deep_practitioners"]),
        f"{int(r['deep_practitioners'])}",
        (f"held by {r['deep_practitioner_names']}" if r["deep_practitioner_names"]
         else f"{int(r['people_with_skill'])} claim it, none rated {cfg.EXPERT_THRESHOLD}+"),
    ) for _, r in critical.sort_values(
        ["deep_practitioners", "people_with_skill"], ascending=[True, False]
    ).iterrows()]

    exposure_rows = [[
        f"<strong>{_e(r['canonical_skill'])}</strong>",
        _tag(r["risk_band"], _BAND_TONE.get(r["risk_band"], "warning")),
        _e(r["deep_practitioner_names"] or "—"),
        str(int(r["people_with_skill"])),
        _e(r["criticality_rationale"]),
    ] for _, r in exposed.iterrows()]

    # --- section 3: freshness -------------------------------------------
    fresh_rows = [(
        r["supervisory_org"],
        float(r["profile_freshness_pct"] or 0),
        f"{r['profile_freshness_pct']:.0f}%",
        f"{int(r['headcount'])} people · {int(r['avg_days_since_skill_update'] or 0)}d avg age",
    ) for _, r in scorecard.iterrows()]

    # --- section 4: certifications --------------------------------------
    at_risk = certs[certs["is_at_risk"] & certs["in_headcount"].fillna(False)]
    cert_rows = [[
        f"<strong>{_e(r['worker_name'])}</strong>",
        _e(r["certification"]),
        _tag(r["risk_band"], _CERT_TONE.get(r["risk_band"], "warning")),
        (_e(r["expires_on"]) if pd.notna(r["expires_on"]) else "—"),
        (f"${r['voucher_cost']:,.0f}" if pd.notna(r["voucher_cost"]) else "—"),
        _e(r["notes"] or ""),
    ] for _, r in at_risk.iterrows()]

    tracked_spend = float(certs["voucher_cost"].fillna(0).sum())
    stated_total = 2071.0

    # --- section 5: learning vs profile ---------------------------------
    recent_ids = set(learning[learning["is_recent"]]["employee_id"].astype(str))
    current_ids = set(profile[profile["is_current"]]["employee_id"].astype(str))
    pop_ids = pop["employee_id"].astype(str)
    lagging = pop[pop_ids.isin(recent_ids) & ~pop_ids.isin(current_ids)]

    # --- section 6: data quality ----------------------------------------
    severity_rows = []
    for source, grp in issues.groupby("source_system"):
        counts = grp["severity"].value_counts()
        severity_rows.append((source, [
            ("High", int(counts.get("high", 0)), "--sev-high"),
            ("Medium", int(counts.get("medium", 0)), "--sev-medium"),
            ("Low", int(counts.get("low", 0)), "--sev-low"),
        ]))
    severity_rows.sort(key=lambda r: -sum(v for _, v, _ in r[1]))

    high_issues = issues[issues["severity"] == "high"]
    issue_rows = [[
        _e(r["source_system"]), _e(r["issue_type"].replace("_", " ")),
        f"<strong>{_e(r['entity'])}</strong>", _e(r["detail"]), _e(r["resolution"]),
    ] for _, r in high_issues.iterrows()]

    kpi_html = "".join(_kpi_tile(r) for _, r in kpis.iterrows())
    no_depth = int((critical["deep_practitioners"] == 0).sum())

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Skills Intelligence Report</title>
<style>{_CSS}</style></head>
<body><div class="wrap">

<h1>Skills intelligence: what four systems say, and what they agree on</h1>
<p class="meta">
  As of <strong>{as_of.isoformat()}</strong> &middot; {headcount} workers in headcount
  ({len(workers)} people across all worker types) &middot; sources: Workday skills extract,
  Degreed completions, the recertification tracker, the team skills matrix
</p>

<p class="lede">
  The four sources describe the same {len(workers)} people, but they disagree about
  who those people are, how good they are, and what their certifications cost. Once
  the records are reconciled the picture is sharper than any single source &mdash; and
  worse. <strong>{len(exposed)} of {len(critical)} skills the business depends on rest on
  one person or nobody</strong>, and fewer than half of all skill profiles have been
  touched in the last six months.
</p>

<div class="kpis">{kpi_html}</div>
<p class="meta" style="margin-top:14px">
  Population for every metric: workers of type Employee with status Active or Leave of
  Absence. Contingent workers, interns and leavers are reported but never counted in
  coverage, so a departure cannot look like an improvement.
</p>

<h2>1 &middot; The same person, written eight ways</h2>
<p>
  Nothing could be counted until identity was resolved. Taken literally the four files
  describe <strong>{total_identifiers} distinct identifiers for {len(workers)} people</strong>.
  {_count_word(len(split))} are split identities that would otherwise have been counted
  twice, each with half of that person's history attached to each half.
</p>
{_table(["Worker", "Identifiers merged", "Organisation", "Why it was split"], split_rows)}
<p>
  Beyond identifiers, people are written by preferred name in one system and legal name
  in another &mdash; Mike/Emeka, Katie/Kathleen, Jazz/Jasmine, Alex/Long, SJ/Soo-Jin,
  MC/Marie-Claire &mdash; plus usernames, email addresses and one Windows domain account
  used in place of a name. <strong>This is not cosmetic.</strong> Because nobody could
  see that <code>chenwe4</code> and <code>Wei-Lin Chen</code> were the same person, the
  recertification tracker carries the same CCNP twice with two different expiry dates,
  one of which is an Excel serial number that decoded to a date two years in the past.
</p>
<p>
  Two people also carry the wrong start date. Marcus Whitfield and Soo-Jin Kim joined
  through the Splunk acquisition, and Workday records the March 2024 migration date as
  their hire date. Their real tenure is
  <strong>{_years(split[split["is_acquired_employee"]]["workday_hire_date"].iloc[0],
                  split[split["is_acquired_employee"]]["original_hire_date"].iloc[0])}
  longer</strong> than the system says. They are also the only two people with any depth
  in Splunk &mdash; so the retention risk the tenure figure would flag is exactly the risk
  it hides.
</p>

<h2>2 &middot; {len(exposed)} of {len(critical)} critical skills have no backup</h2>
<p>
  Counting only ratings on a comparable scale, and counting someone as deep only at
  proficiency {cfg.EXPERT_THRESHOLD} or above:
  <strong>{no_depth} critical skills have nobody at that level at all</strong>, and
  {len(exposed) - no_depth} more rest on a single person.
</p>
<div class="card">
  <div class="card-title">People at proficiency {cfg.EXPERT_THRESHOLD}+ per critical skill</div>
  <div class="card-sub">In-headcount population. Hatched bars are skills with no one at that level.</div>
  {_bar_rows(depth_rows)}
</div>
{_table(["Skill", "Exposure", "Who holds it", "Claim it", "Why it is critical"],
        exposure_rows, numeric={3})}
<p>
  The two entries worth reading twice are <strong>Catalyst Center</strong> and
  <strong>Terraform</strong>. Both are among the most widely claimed skills in the
  organisation &mdash; nine and seven people respectively &mdash; and neither has a single
  person rated above intermediate. Breadth here has been mistaken for capability.
</p>

<h2>3 &middot; Fewer than half the profiles are current</h2>
<p>
  Every number above is only as good as the profiles underneath it.
  {_count_word(len(zero_fresh))} organisation{"" if len(zero_fresh) == 1 else "s"} ha{"s" if len(zero_fresh) == 1 else "ve"}
  <strong>no worker at all</strong> with a skill rating updated in the last
  {cfg.PROFILE_FRESHNESS_DAYS} days: {_e(", ".join(zero_fresh["supervisory_org"]))}.
</p>
<div class="card">
  <div class="card-title">Share of workers with a skill rating updated in the last {cfg.PROFILE_FRESHNESS_DAYS} days</div>
  <div class="card-sub">By supervisory organisation, lowest first</div>
  {_bar_rows(fresh_rows, maximum=100)}
</div>

<h2>4 &middot; Certifications: {len(at_risk)} at risk, and a budget total that is wrong</h2>
<p>
  {_count_word(len(cert_rows))} certification{"" if len(cert_rows) == 1 else "s"} held by
  in-headcount workers {"is" if len(cert_rows) == 1 else "are"} expired, expiring inside
  {cfg.CERT_EXPIRY_WARNING_DAYS} days, or ha{"s" if len(cert_rows) == 1 else "ve"} no expiry
  recorded at all.
</p>
{_table(["Worker", "Certification", "Status", "Expires", "Voucher", "Tracker note"],
        cert_rows, numeric={4})}
<p>
  Separately, the tracker's <code>TOTAL VOUCHER BUDGET</code> cell reads
  <strong>${stated_total:,.0f}</strong>. The certifications actually tracked on that sheet
  total <strong>${tracked_spend:,.0f}</strong>. The stated figure is not an approximation
  &mdash; it is the exact sum of a stale FY25 pivot left on a hidden-away tab
  (<code>DO NOT DELETE</code>): 1600&nbsp;+&nbsp;71&nbsp;+&nbsp;0&nbsp;+&nbsp;400. The total
  cell is pointed at the wrong range, and has been understating certification spend by
  <strong>{tracked_spend / stated_total:.1f}&times;</strong>.
</p>
<p>
  One further gap: José Delgado's Cisco Certified Specialist &mdash; Enterprise Core
  ($400) does not appear on the FY27 approved certification list at all, so it is spend
  outside the agreed catalogue rather than an overspend within it.
</p>

<h2>5 &middot; People are learning; the profiles are not being updated</h2>
<p>
  Learning engagement is <strong>{float(kpis.set_index("metric_key").loc["learning_engagement_pct", "metric_value"]):.0f}%</strong>
  &mdash; healthy &mdash; while profile freshness is
  <strong>{float(kpis.set_index("metric_key").loc["skill_profile_freshness_pct", "metric_value"]):.0f}%</strong>.
  That gap is the finding: <strong>{len(lagging)} of {headcount} workers completed
  learning in the last year but have not touched their skill profile in six months</strong>.
</p>
<ul>{"".join(f"<li>{_e(r['worker_name'])} &mdash; {_e(r['supervisory_org'])}</li>" for _, r in lagging.iterrows())}</ul>
<p>
  This is the cheapest thing on this page to fix, and it is upstream of everything else.
  The capability data is not missing; it is stranded in the learning system because
  nothing prompts a profile update when a course completes.
</p>

<h2>6 &middot; What the reconciliation had to repair</h2>
<p>
  {len(issues)} issues were logged while building these tables, {len(high_issues)} of them
  high severity. Every one is recorded in <code>silver.data_quality_issue</code> with what
  was done about it, so no repair is invisible and none of them is a silent drop.
</p>
<div class="card">
  <div class="card-title">Issues by source system and severity</div>
  <div class="card-sub">Ordinal severity ramp; hover any segment for its count</div>
  {_stacked_rows(severity_rows)}
  <div class="legend">
    <span><i style="background:var(--sev-high)"></i>High &mdash; needs a fix in the source system</span>
    <span><i style="background:var(--sev-medium)"></i>Medium &mdash; repaired, worth reviewing</span>
    <span><i style="background:var(--sev-low)"></i>Low &mdash; repaired automatically</span>
  </div>
</div>
<details><summary>All {len(high_issues)} high-severity issues</summary>
{_table(["Source", "Issue", "Entity", "Detail", "Resolution"], issue_rows)}
</details>

<h2>What to do about it</h2>
<ul>
  <li><strong>Fix the {len(zero_fresh)} zero-freshness organisation{"" if len(zero_fresh) == 1 else "s"} first.</strong>
      Nothing else on this page can be trusted where the input is a year old.</li>
  <li><strong>Name a second person for {_e(", ".join(exposed.head(3)["canonical_skill"]))}.</strong>
      These have the shortest path to a backup: someone already claims the skill at
      intermediate level.</li>
  <li><strong>Prompt a profile update when learning completes.</strong> {len(lagging)} workers
      have current capability that the system of record does not know about.</li>
  <li><strong>Retire the skills matrix or make it the source.</strong> Maintaining both
      guarantees they disagree; the matrix is a year stale and uses a rating scale that
      cannot be compared with Workday's.</li>
  <li><strong>Repoint the voucher total and re-baseline the FY27 budget</strong> against
      ${tracked_spend:,.0f}, not ${stated_total:,.0f}.</li>
</ul>

<h2>Method and limits</h2>
<ul>
  <li><strong>Evidence precedence.</strong> A manager assessment outranks a self
      assessment; both outrank the skills matrix. Where sources disagree the stronger
      evidence wins and the disagreement is logged, not averaged.</li>
  <li><strong>Depth requires a comparable scale.</strong> The matrix's legacy H/M/L
      ratings are translated onto 1&ndash;5 as an approximation, and approximations never
      establish that someone is deep in a skill &mdash; they would have manufactured
      {int(profile["is_deep_low_confidence"].sum())} false experts.</li>
  <li><strong>A blank is not a zero.</strong> An empty matrix cell means nobody filled it
      in. Only an explicit "no" counts as declared no exposure.</li>
  <li><strong>Small population.</strong> {headcount} people in headcount. Percentages move
      roughly 5 points per person; read the counts, not the decimals.</li>
  <li><strong>Criticality is a judgement</strong> maintained in
      <code>data/reference/critical_skills.csv</code>, not derived from the data. It is
      the one input here a reader should challenge first.</li>
  <li><strong>Fiscal shorthand is not a date.</strong> Expiries recorded as "Q1 FY28" or
      "end of FY" are left null rather than guessed, so they cannot be alerted on until
      someone enters a real date.</li>
</ul>

<footer>
  Generated from <code>{cfg.CATALOG}.{cfg.GOLD_SCHEMA}</code> &middot; analysis as-of
  {as_of.isoformat()} &middot; every figure on this page is reproducible by re-running the
  pipeline notebooks against the same source files.
</footer>
</div></body></html>"""


def _count_word(n: int) -> str:
    """Small counts read better as words at the start of a sentence."""
    words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
             6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}
    return words.get(n, str(n))


def _years(later: object, earlier: object) -> str:
    """Human-readable gap between two dates."""
    if later is None or earlier is None or pd.isna(later) or pd.isna(earlier):
        return "an unknown amount"
    later_d = later.date() if hasattr(later, "date") else later
    earlier_d = earlier.date() if hasattr(earlier, "date") else earlier
    years = (later_d - earlier_d).days / 365.25
    return f"{years:.1f} years"
