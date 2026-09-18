# Findings

Analysis as of **2026-09-01** (the date of the Workday extract). 25 people across
all worker types; **21 in headcount** — employees with status Active or Leave of
Absence. Contingent workers, interns and leavers are reported but never counted
in coverage, so a departure cannot look like an improvement.

The rendered version with charts is `build/skills_report.html`, produced by
`local/run_analysis.py` and by notebook `04`.

---

## 1 · The same person, written eight ways

Nothing could be counted until identity was resolved. Taken literally, the four
files describe **28 distinct identifiers for 25 people**.

| Worker | Identifiers merged | Why it was split |
|---|---|---|
| Marcus Whitfield | `SPLK-0227` → `1048893` | Legacy Splunk worker ID kept on one pre-migration row |
| Soo-Jin Kim | `SPLK-0314` → `1041555` | Legacy Splunk worker ID kept on one pre-migration row |
| Wei-Lin Chen | `44102` → `1044102` | Leading `10` dropped on three Workday rows |

Beyond identifiers, people appear by preferred name in one system and legal name
in another — Mike/Emeka, Katie/Kathleen, Jazz/Jasmine, Alex/Long, SJ/Soo-Jin,
MC/Marie-Claire — plus usernames, email addresses, and one Windows domain account
(`CISCO\delgadj`) used in place of a name.

**This is not cosmetic.** Because nobody could see that `chenwe4` and
`Wei-Lin Chen` were the same person, the recertification tracker carries the same
CCNP Enterprise twice with two different expiry dates — one of them an Excel
serial number that decoded to `2024-01-01`, sitting next to a status of
"Expiring". The pipeline keeps the record whose expiry is consistent with its own
status (`2026-10-15`) and logs the conflict.

### Acquisition tenure is understated

Marcus Whitfield and Soo-Jin Kim joined through the Splunk acquisition. Workday
records **2024-03-18** — the migration date — as their hire date. Their real start
dates are 2019-04-15 and 2020-03-14, so their tenure is understated by **4.9 and
4.0 years**.

They are also the only two people with any depth in Splunk SPL or Splunk
Enterprise Security. The retention risk a tenure figure would flag is exactly the
risk the wrong tenure figure hides.

---

## 2 · Ten of fifteen critical skills have no backup

Counting only ratings on a comparable scale, and counting someone as deep only at
proficiency 4+:

| Exposure | Count | Skills |
|---|---|---|
| **No depth** — claimed but nobody at 4+ | 4 | Catalyst Center, Cisco IOS XE, Terraform, ThousandEyes |
| **Single point of failure** — exactly one person | 6 | ACI, BGP, Cisco Secure Firewall, NX-OS, VXLAN EVPN, Zero Trust Architecture |
| **Thin** — two people | 4 | Kubernetes, SD-WAN, Splunk Enterprise Security, Splunk SPL |
| **Covered** — three or more | 1 | Python |

Two entries deserve a second read. **Catalyst Center** is claimed by nine people
and **Terraform** by seven — the two most widely claimed critical skills in the
organisation — and neither has a single person rated above intermediate. Breadth
has been mistaken for capability.

Concentrations by person:

- **Emeka Okonkwo** is the sole deep practitioner of both NX-OS and VXLAN EVPN.
- **Daniel P. O'Leary** is the sole deep practitioner of both ACI and BGP, and the
  only Advanced Cisco IOS XE rating in the file belonged to Rosa Maldonado, who
  has left.
- **Greta Schmidt** is the sole deep practitioner of Zero Trust Architecture.
- **Kwame Boateng** is the sole deep practitioner of Cisco Secure Firewall.

---

## 3 · Fewer than half the profiles are current

**47.6%** of in-headcount workers have a skill rating updated in the last 180
days. Three organisations have no worker at all with a current profile:

| Organisation | Headcount | Freshness | Avg age of rating |
|---|---:|---:|---:|
| CX Americas Delivery | 3 | 0% | 305 days |
| Global Enterprise Sales Engineering | 2 | 0% | 190 days |
| Webex Platform Engineering | 1 | 0% | 372 days |

One worker — Nana Osei, hired 2026-08-31, one day before the extract — has no
skill profile at all. That is expected for a new starter and is the reason
profile coverage and profile freshness are tracked as separate metrics.

---

## 4 · Certifications: three at risk, and a budget total that is wrong

| Worker | Certification | Status | Expires | Voucher |
|---|---|---|---|---:|
| Ivana Petrov | CCNA | **Expired** | 2026-03-02 | $300 |
| Wei-Lin Chen | CCNP Enterprise | **Expiring within 90 days** | 2026-10-15 | $800 |
| Sana Ahmed | CCNP Enterprise | **No expiry recorded** | — | $0 |

Three more certifications lapse within twelve months (Emeka Okonkwo's CCIE in 194
days, Kwame Boateng's CCNP Security, Yuki Nakamura's DevNet Professional).

### The budget total points at the wrong range

The tracker's `TOTAL VOUCHER BUDGET` cell reads **$2,071**. The certifications
actually tracked on that sheet total **$6,226**.

The stated figure is not an approximation. It is the exact sum of a stale FY25
pivot left on the `DO NOT DELETE` tab: `1600 + 71 + 0 + 400`. The total cell is
pointed at the wrong range and has been understating certification spend by
**3.0×**.

One further gap: José Delgado's Cisco Certified Specialist — Enterprise Core
($400) does not appear on the FY27 approved certification list at all, so it is
spend outside the agreed catalogue rather than an overspend within it.

---

## 5 · People are learning; the profiles are not being updated

Learning engagement is **76%** while profile freshness is **48%**. That gap is the
finding: **7 of 21 workers completed learning in the last year but have not
touched their skill profile in six months** — Daniel P. O'Leary, Erik Lindqvist,
Greta Schmidt, Ivana Petrov, José R. Delgado, Kathleen Brennan, Ngozi Achebe.

This is the cheapest thing on this list to fix, and it is upstream of everything
else. The capability data is not missing; it is stranded in the learning system
because nothing prompts a profile update when a course completes.

---

## 6 · What the reconciliation had to repair

28 issues logged, **15 high severity**. All are in `silver.data_quality_issue`
with their resolution.

| Source | High-severity issues |
|---|---|
| Workday | 5 identity conflicts, 2 conflicting hire dates, 1 conflicting rating, 1 worker with no skill profile |
| Recertification tracker | 3 duplicate certifications, 1 row with the status and expiry columns swapped |
| Degreed | 1 row where the identity columns had shifted one place left |
| Skills matrix | 1 person on two rows, 1 column covering two distinct skills |

Notable individual repairs:

- **Swapped columns.** Alex Vo's CKA row has the expiry date in the status column
  and "Active" in the expiry column. Detected by type, not by position, and
  swapped back.
- **Shifted columns.** One Degreed row has the employee ID in the email column and
  the name in the employee ID column.
- **A conflated matrix column.** The matrix's `ACI / NX-OS` column covers two
  distinct skills, so no rating in it can be attributed to either. It is excluded
  from coverage rather than assigned to one — which would have manufactured four
  false experts.
- **Duplicate learning.** "VXLAN EVPN Deep Dive" and "VXLAN EVPN Deep Dive (Rev 2)"
  on the same day for the same person is one completion.
- **Mixed units.** One learning duration is recorded as "90 min" where every other
  row is in hours.

---

## What to do about it

1. **Fix the three zero-freshness organisations first.** Nothing else here can be
   trusted where the input is a year old.
2. **Name a second person for Catalyst Center, Cisco IOS XE and Terraform.** These
   have the shortest path to a backup: people already claim them at intermediate.
3. **Prompt a profile update when learning completes.** Seven workers have current
   capability the system of record does not know about.
4. **Retire the skills matrix or make it the source.** Maintaining both guarantees
   they disagree; it is a year stale and its rating scale cannot be compared with
   Workday's.
5. **Repoint the voucher total** and re-baseline FY27 against $6,226, not $2,071.

## Limits

- 21 people in headcount. Percentages move roughly five points per person.
- Skill criticality is a maintained judgement in
  `data/reference/critical_skills.csv`, not derived from the data.
- Evidence precedence is a rule, not a fact: manager assessment > self assessment
  > skills matrix. Where sources disagree the stronger evidence wins and the
  disagreement is logged, never averaged.
- Expiries recorded as fiscal shorthand are left null rather than guessed.
