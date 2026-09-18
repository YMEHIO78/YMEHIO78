"""Silver and gold transforms.

Silver conforms each source onto shared keys and logs every repair it makes.
Gold answers the questions the report and dashboard ask. All of it is pandas:
the whole dataset is a few hundred rows, so driver-side pandas is both faster
and clearer than Spark here, while the outputs still land as Delta tables in
Unity Catalog for SQL and dashboard consumers. Swap these for Spark DataFrame
operations if the population ever outgrows a single node.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from . import config as cfg
from .normalize import (
    canonical_skill,
    clean_text,
    date_is_fiscal_shorthand,
    norm_key,
    normalize_cert_status,
    normalize_learning_status,
    normalize_location,
    normalize_org,
    normalize_person_name,
    normalize_proficiency,
    parse_date,
    parse_duration_hours,
    parse_money,
    parse_number,
    resolve_employee_id,
)
from .reference import critical_skill_rationale, critical_skills

# Proficiency evidence precedence: a manager's assessment outranks a self
# rating, an unattributed Workday rating outranks the hand-maintained
# spreadsheet, and the spreadsheet is corroborating evidence only.
_SOURCE_RANK = {
    "Manager Assessment": 3.0,
    "Self-Assessment": 2.0,
    "Unspecified": 1.5,
    "Skills Matrix": 1.0,
}


class DQLog:
    """Collects every repair, drop and conflict the pipeline decides on."""

    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = []

    def add(self, *, source: str, issue_type: str, severity: str, entity: str | None,
            detail: str, action: str) -> None:
        self._rows.append({
            "source_system": source,
            "issue_type": issue_type,
            "severity": severity,
            "entity": entity or "",
            "detail": detail,
            "resolution": action,
        })

    def frame(self) -> pd.DataFrame:
        cols = ["source_system", "issue_type", "severity", "entity", "detail", "resolution"]
        return pd.DataFrame(self._rows, columns=cols)


# --------------------------------------------------------------------------
# Silver: workers
# --------------------------------------------------------------------------

def build_worker_dim(workday_raw: pd.DataFrame, dq: DQLog) -> pd.DataFrame:
    """One row per person, with identity and tenure conflicts resolved."""
    records = []
    for _, row in workday_raw.iterrows():
        source_id = clean_text(row["Employee ID"])
        emp_id, reason = resolve_employee_id("workday", source_id)
        if emp_id is None:
            emp_id = source_id
        elif emp_id != source_id and reason:
            dq.add(source="Workday", issue_type="identity_conflict", severity="high",
                   entity=f"{clean_text(row['Worker'])} ({source_id})",
                   detail=reason, action=f"Mapped to employee ID {emp_id}")
        records.append({
            "employee_id": emp_id,
            "source_employee_id": source_id,
            "worker_name": normalize_person_name(row["Worker"]),
            "business_title": clean_text(row["Business Title"]),
            "job_profile": clean_text(row["Job Profile"]),
            "supervisory_org": normalize_org(row["Supervisory Organization"]),
            "cost_center": clean_text(row["Cost Center"]),
            "location": normalize_location(row["Location"]),
            "worker_type": clean_text(row["Worker Type"]),
            "worker_status": clean_text(row["Worker Status"]),
            "hire_date": parse_date(row["Hire Date"]),
            "manager_name": normalize_person_name(row["Manager"]),
        })

    df = pd.DataFrame(records)

    # Locations arrive both as site codes and full names; keep the fullest form.
    workers = []
    for emp_id, grp in df.groupby("employee_id", sort=False):
        hire_dates = sorted({d for d in grp["hire_date"] if d is not None})
        if len(hire_dates) > 1:
            dq.add(source="Workday", issue_type="conflicting_attribute", severity="high",
                   entity=f"{grp['worker_name'].iloc[0]} ({emp_id})",
                   detail=("Two hire dates present: "
                           + ", ".join(d.isoformat() for d in hire_dates)
                           + " - the later date is the acquisition migration date, not the real start"),
                   action=f"original_hire_date set to {hire_dates[0].isoformat()}; "
                          f"workday_hire_date kept as {hire_dates[-1].isoformat()}")
        locations = [loc for loc in grp["location"] if loc]
        best_location = max(locations, key=len) if locations else None

        legacy_ids = sorted({sid for sid in grp["source_employee_id"] if sid and sid != emp_id})
        workers.append({
            "employee_id": emp_id,
            "worker_name": _mode(grp["worker_name"]),
            "business_title": _mode(grp["business_title"]),
            "job_profile": _mode(grp["job_profile"]),
            "supervisory_org": _mode(grp["supervisory_org"]),
            "cost_center": _mode(grp["cost_center"]),
            "location": best_location,
            "worker_type": _mode(grp["worker_type"]),
            "worker_status": _mode(grp["worker_status"]),
            "original_hire_date": hire_dates[0] if hire_dates else None,
            "workday_hire_date": hire_dates[-1] if hire_dates else None,
            "manager_name": _mode(grp["manager_name"]),
            "legacy_worker_ids": ";".join(legacy_ids),
            "is_acquired_employee": bool(any(sid.upper().startswith("SPLK") for sid in legacy_ids)),
        })

    out = pd.DataFrame(workers)
    out["in_headcount"] = (
        out["worker_type"].isin(cfg.HEADCOUNT_WORKER_TYPES)
        & out["worker_status"].isin(cfg.IN_SCOPE_WORKER_STATUSES)
    )
    out["tenure_years"] = out["original_hire_date"].map(
        lambda d: round((cfg.AS_OF_DATE - d).days / 365.25, 1) if d else None
    )
    return out.sort_values("worker_name").reset_index(drop=True)


def _mode(series: pd.Series) -> object:
    """Most frequent non-null value, first occurrence wins ties."""
    vals = [v for v in series if v is not None and v == v and v != ""]
    if not vals:
        return None
    counts: dict[object, int] = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    return max(vals, key=lambda v: (counts[v], -vals.index(v)))


# --------------------------------------------------------------------------
# Silver: skills from Workday
# --------------------------------------------------------------------------

def build_worker_skills(workday_raw: pd.DataFrame, workers: pd.DataFrame, dq: DQLog) -> pd.DataFrame:
    """Conform Workday skill rows, then resolve duplicates and rating conflicts."""
    id_map = dict(zip(workers["employee_id"], workers["worker_name"]))
    rows = []
    for idx, row in workday_raw.iterrows():
        source_id = clean_text(row["Employee ID"])
        emp_id, _ = resolve_employee_id("workday", source_id)
        emp_id = emp_id or source_id
        raw_skill = clean_text(row["Skill"])
        person = id_map.get(emp_id) or normalize_person_name(row["Worker"])

        if raw_skill is None:
            dq.add(source="Workday", issue_type="missing_skill_profile", severity="high",
                   entity=f"{person} ({emp_id})",
                   detail="Worker row present with no skill, category, rating or source",
                   action="Counted as a worker with no skill profile")
            continue

        skill, domain = canonical_skill(raw_skill)
        if skill is None:
            dq.add(source="Workday", issue_type="unmapped_skill", severity="medium",
                   entity=f"{person} ({emp_id})",
                   detail=f"Skill {raw_skill!r} is not in the alias table",
                   action="Kept verbatim and excluded from skill roll-ups")
            skill, domain = raw_skill, clean_text(row["Skill Category"])

        proficiency, confidence = normalize_proficiency(row["Proficiency Rating"])
        raw_rating = clean_text(row["Proficiency Rating"])
        if proficiency is None and raw_rating:
            dq.add(source="Workday", issue_type="unrated_skill", severity="low",
                   entity=f"{person} ({emp_id})",
                   detail=f"{skill}: rating {raw_rating!r} carries no level",
                   action="Proficiency left null")
        elif raw_rating is None:
            dq.add(source="Workday", issue_type="unrated_skill", severity="medium",
                   entity=f"{person} ({emp_id})",
                   detail=f"{skill}: no proficiency rating recorded",
                   action="Proficiency left null")

        last_updated = parse_date(row["Last Updated"])
        if last_updated is None and clean_text(row["Last Updated"]):
            dq.add(source="Workday", issue_type="unparseable_date", severity="medium",
                   entity=f"{person} ({emp_id})",
                   detail=f"{skill}: Last Updated {clean_text(row['Last Updated'])!r} is not a date",
                   action="Treated as missing")

        rows.append({
            "employee_id": emp_id,
            "worker_name": person,
            "raw_skill": raw_skill,
            "canonical_skill": skill,
            "skill_domain": domain,
            "proficiency": proficiency,
            "proficiency_confidence": confidence,
            "years_experience": parse_number(row["Years of Experience"]),
            "assessment_source": clean_text(row["Skill Source"]) or "Unspecified",
            "last_updated": last_updated,
            "source_row": int(idx) + 2,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Byte-identical repeats of the same rating: drop silently but count them.
    dup_cols = ["employee_id", "canonical_skill", "proficiency", "assessment_source", "last_updated"]
    exact_dupes = df.duplicated(subset=dup_cols, keep="first")
    for _, row in df[exact_dupes].iterrows():
        dq.add(source="Workday", issue_type="duplicate_row", severity="low",
               entity=f"{row['worker_name']} ({row['employee_id']})",
               detail=f"{row['canonical_skill']} rating repeated verbatim on row {row['source_row']}",
               action="Duplicate dropped")
    df = df[~exact_dupes].copy()

    # Competing ratings for one skill: keep the strongest evidence.
    df["_rank"] = df["assessment_source"].map(lambda s: _SOURCE_RANK.get(s, 0))
    df["_recency"] = df["last_updated"].map(lambda d: d.toordinal() if d else 0)
    resolved = []
    for (emp_id, skill), grp in df.groupby(["employee_id", "canonical_skill"], sort=False):
        if len(grp) > 1:
            levels = sorted({int(p) for p in grp["proficiency"] if p is not None})
            if len(levels) > 1:
                detail = (f"{skill}: conflicting ratings "
                          + ", ".join(
                              f"{int(r['proficiency'])} ({r['assessment_source']}, "
                              f"{r['last_updated'].isoformat() if r['last_updated'] else 'no date'})"
                              for _, r in grp.sort_values("_rank", ascending=False).iterrows()
                              if r["proficiency"] is not None)
                          )
                dq.add(source="Workday", issue_type="conflicting_rating", severity="high",
                       entity=f"{grp['worker_name'].iloc[0]} ({emp_id})", detail=detail,
                       action="Kept the manager assessment, else the most recent rating")
        best = grp.sort_values(["_rank", "_recency"], ascending=False).iloc[0]
        resolved.append(best)

    out = pd.DataFrame(resolved).drop(columns=["_rank", "_recency"])
    out["days_since_update"] = out["last_updated"].map(
        lambda d: (cfg.AS_OF_DATE - d).days if d else None
    )
    out["is_current"] = out["days_since_update"].map(
        lambda d: bool(d is not None and d <= cfg.PROFILE_FRESHNESS_DAYS)
    )
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------
# Silver: the manual skills matrix
# --------------------------------------------------------------------------

def build_matrix_ratings(matrix_raw: pd.DataFrame, dq: DQLog) -> pd.DataFrame:
    """Resolve matrix rows to employee IDs and translate the mixed rating dialects."""
    rows = []
    unresolved: set[str] = set()
    conflated_reported: set[str] = set()
    for _, row in matrix_raw.iterrows():
        name = clean_text(row["name"])
        emp_id, reason = resolve_employee_id("matrix", name)
        if emp_id is None:
            if name and name not in unresolved:
                unresolved.add(name)
                dq.add(source="Skills Matrix", issue_type="unresolved_identity", severity="high",
                       entity=name, detail="Matrix name matches no Workday worker",
                       action="Row excluded from analytics")
            continue
        if emp_id == "":
            if name not in unresolved:
                unresolved.add(name)
                dq.add(source="Skills Matrix", issue_type="out_of_scope_person", severity="medium",
                       entity=name, detail=reason or "Not part of the Workday population",
                       action="Row excluded from headcount and coverage analytics")
            continue

        skill, domain = canonical_skill(row["skill"])
        if skill is None:
            continue
        if skill.endswith("(conflated)") and skill not in conflated_reported:
            conflated_reported.add(skill)
            dq.add(source="Skills Matrix", issue_type="ambiguous_skill_column", severity="high",
                   entity=clean_text(row["skill"]),
                   detail="One matrix column covers two distinct skills, so no rating in it can be "
                          "attributed to either",
                   action="Excluded from skill coverage until the column is split at source")
        raw_rating = clean_text(row["rating"])
        if raw_rating is None:
            # A blank cell means nobody filled it in - it is not a statement
            # that the person lacks the skill, so it creates no evidence row.
            continue
        proficiency, confidence = normalize_proficiency(row["rating"])
        rows.append({
            "employee_id": emp_id,
            "matrix_name": name,
            "matrix_section": clean_text(row["matrix_section"]),
            "team": clean_text(row["team"]),
            "canonical_skill": skill,
            "skill_domain": domain,
            "raw_rating": raw_rating,
            "proficiency": proficiency,
            "proficiency_confidence": confidence,
            "is_no_exposure": norm_key(raw_rating) in {"no", "none"},
            "matrix_row": int(row["matrix_row"]),
            "notes": clean_text(row["notes"]),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # The same person appears on two rows of the matrix.
    per_person_rows = df.groupby("employee_id")["matrix_row"].nunique()
    for emp_id, n_rows in per_person_rows.items():
        if n_rows > 1:
            names = sorted(set(df[df["employee_id"] == emp_id]["matrix_name"]))
            dq.add(source="Skills Matrix", issue_type="duplicate_person", severity="high",
                   entity=f"{names[0]} ({emp_id})",
                   detail=f"Appears on {n_rows} matrix rows as {', '.join(repr(n) for n in names)}",
                   action="Kept the row with the most populated ratings")

    keep_rows = (
        df[df["proficiency"].notna()]
        .groupby(["employee_id", "matrix_row"])
        .size()
        .reset_index(name="filled")
        .sort_values(["employee_id", "filled"], ascending=[True, False])
        .drop_duplicates("employee_id")[["employee_id", "matrix_row"]]
    )
    df = df.merge(keep_rows, on=["employee_id", "matrix_row"], how="inner")
    df["assessment_source"] = "Skills Matrix"
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------
# Silver: certifications
# --------------------------------------------------------------------------

def build_certifications(recert_raw: pd.DataFrame, catalogue: pd.DataFrame,
                         workers: pd.DataFrame, dq: DQLog) -> pd.DataFrame:
    """Clean the recert tracker: repair swapped columns, resolve people, dedupe."""
    name_by_id = dict(zip(workers["employee_id"], workers["worker_name"]))
    rows = []
    for idx, row in recert_raw.iterrows():
        engineer = clean_text(row["Engineer"])
        emp_id, reason = resolve_employee_id("recert", engineer)
        source_row = int(idx) + 2

        if emp_id is None:
            dq.add(source="Recert Tracker", issue_type="unresolved_identity", severity="high",
                   entity=engineer or f"row {source_row}",
                   detail="Tracker name matches no Workday worker",
                   action="Row excluded from analytics")
            continue
        if emp_id == "":
            dq.add(source="Recert Tracker", issue_type="out_of_scope_person", severity="medium",
                   entity=engineer, detail=reason or "Not part of the Workday population",
                   action="Row excluded from compliance and budget analytics")
            continue

        status_cell, expires_cell = row["Cert Status"], row["Expires"]
        status = normalize_cert_status(status_cell)
        expires = parse_date(expires_cell)

        # One row has the expiry date in the status column and vice versa.
        if status is None and parse_date(status_cell) is not None:
            swapped_status = normalize_cert_status(expires_cell)
            if swapped_status is not None:
                dq.add(source="Recert Tracker", issue_type="swapped_columns", severity="high",
                       entity=f"{name_by_id.get(emp_id, engineer)} ({emp_id})",
                       detail=f"Cert Status held {clean_text(status_cell)!r} and Expires held "
                              f"{clean_text(expires_cell)!r}",
                       action="Values swapped back into the correct columns")
                status, expires = swapped_status, parse_date(status_cell)

        if expires is None and date_is_fiscal_shorthand(expires_cell):
            dq.add(source="Recert Tracker", issue_type="non_date_expiry", severity="medium",
                   entity=f"{name_by_id.get(emp_id, engineer)} ({emp_id})",
                   detail=f"Expiry recorded as fiscal shorthand {clean_text(expires_cell)!r}",
                   action="Expiry left null - cannot be scheduled or alerted on")
        elif expires is None and clean_text(expires_cell):
            dq.add(source="Recert Tracker", issue_type="unparseable_date", severity="medium",
                   entity=f"{name_by_id.get(emp_id, engineer)} ({emp_id})",
                   detail=f"Expiry {clean_text(expires_cell)!r} is not a date",
                   action="Expiry left null")

        rows.append({
            "employee_id": emp_id,
            "worker_name": name_by_id.get(emp_id, normalize_person_name(engineer)),
            "tracker_name": engineer,
            "certification_raw": clean_text(row["Certification"]),
            "certification": _canonical_cert(row["Certification"]),
            "cert_status": status,
            "expires_on": expires,
            "ce_credits": parse_number(row["CE Credits Earned"]),
            "exam_path": clean_text(row["Exam / Path"]),
            "voucher_cost": parse_money(row["Voucher $"]),
            "mentor": clean_text(row["Who's mentoring"]),
            "notes": clean_text(row["Notes"]),
            "source_row": source_row,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # The same certification is tracked twice for several people under
    # different spellings of both the person and the certification.
    # When the same certification is tracked twice, keep the record whose expiry
    # is consistent with its own status. One row carries an Excel serial that
    # decoded to a date years before the status it sits next to.
    df["_rank"] = df.apply(
        lambda r: (r["expires_on"] is not None) * 4
        + (r["cert_status"] is not None) * 2
        + _status_matches_expiry(r["cert_status"], r["expires_on"]),
        axis=1,
    )
    resolved = []
    for (emp_id, cert), grp in df.groupby(["employee_id", "certification"], sort=False):
        if len(grp) > 1:
            variants = " vs ".join(
                f"{r['certification_raw']!r} (expires "
                f"{r['expires_on'].isoformat() if r['expires_on'] else 'unknown'}, "
                f"voucher {r['voucher_cost']})"
                for _, r in grp.iterrows()
            )
            conflicting = len({r["expires_on"] for _, r in grp.iterrows()}) > 1
            dq.add(source="Recert Tracker", issue_type="duplicate_certification",
                   severity="high" if conflicting else "medium",
                   entity=f"{grp['worker_name'].iloc[0]} ({emp_id})",
                   detail=f"{cert} tracked {len(grp)} times: {variants}",
                   action="Kept the most complete record"
                          + ("; expiry dates disagree and need a human decision" if conflicting else ""))
        resolved.append(grp.sort_values("_rank", ascending=False).iloc[0])

    out = pd.DataFrame(resolved).drop(columns=["_rank"])

    # Voucher cost against the approved price list.
    price_by_cert = {
        _canonical_cert(r["certification"]): parse_money(r["list_price"])
        for _, r in catalogue.iterrows()
    }
    out["list_price"] = out["certification"].map(price_by_cert)
    return out.reset_index(drop=True)


def _status_matches_expiry(status: str | None, expires_on: date | None) -> int:
    """1 when a status and an expiry date tell the same story, else 0.

    A row reading "Expiring" next to a date two years in the past is a corrupted
    cell, not a fact, so consistency decides which duplicate survives.
    """
    if status is None or expires_on is None:
        return 0
    days = (expires_on - cfg.AS_OF_DATE).days
    if status == "Expired":
        return int(days < 0)
    if status == "Expiring":
        return int(0 <= days <= 2 * cfg.CERT_EXPIRY_WARNING_DAYS)
    if status == "Active":
        return int(days > 0)
    return 0


_CERT_ALIASES = {
    "ccie enterprise infrastructure": "CCIE Enterprise Infrastructure",
    "ccie ent infra": "CCIE Enterprise Infrastructure",
    "ccie enterprise infrastructure (lab)": "CCIE Enterprise Infrastructure",
    "ccie enterprise wireless": "CCIE Enterprise Wireless",
    "ccnp enterprise": "CCNP Enterprise",
    "ccnp ent": "CCNP Enterprise",
    "ccnp enterprise (encor + concentration)": "CCNP Enterprise",
    "ccnp security": "CCNP Security",
    "ccnp collaboration": "CCNP Collaboration",
    "ccna": "CCNA",
    "devnet professional": "Cisco Certified DevNet Professional",
    "cisco certified devnet professional": "Cisco Certified DevNet Professional",
    "devnet associate": "Cisco Certified DevNet Associate",
    "cisco certified devnet associate": "Cisco Certified DevNet Associate",
    "cisco certified specialist - enterprise core": "Cisco Certified Specialist - Enterprise Core",
    "splunk enterprise certified admin": "Splunk Enterprise Certified Admin",
    "splunk core certified power user": "Splunk Core Certified Power User",
    "cka (kubernetes administrator)": "Certified Kubernetes Administrator",
    "certified kubernetes administrator": "Certified Kubernetes Administrator",
    "hashicorp terraform associate": "Terraform Associate",
    "terraform associate": "Terraform Associate",
}


def _canonical_cert(value: object) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    return _CERT_ALIASES.get(norm_key(text), text)


# --------------------------------------------------------------------------
# Silver: learning completions
# --------------------------------------------------------------------------

def build_learning(degreed_raw: pd.DataFrame, workers: pd.DataFrame, dq: DQLog) -> pd.DataFrame:
    """Clean Degreed completions: repair the shifted row, resolve identities, dedupe."""
    name_by_id = dict(zip(workers["employee_id"], workers["worker_name"]))
    rows = []
    reported_out_of_scope: set[str] = set()

    for idx, row in degreed_raw.iterrows():
        source_row = int(idx) + 6  # header sits on sheet row 5
        email, emp_col, name = (clean_text(row["User Email"]), clean_text(row["Employee ID"]),
                                clean_text(row["Name"]))

        # A row where the identity block slid one column to the left.
        if email and "@" not in email and "\\" not in email and email.isdigit():
            dq.add(source="Degreed", issue_type="shifted_columns", severity="high",
                   entity=f"{emp_col or name} (sheet row {source_row})",
                   detail=f"Employee ID {email!r} sits in the User Email column and the "
                          f"name in the Employee ID column",
                   action="Identity read from the shifted columns")

        emp_id, reason = resolve_employee_id("degreed", email, emp_col)
        if emp_id is None:
            dq.add(source="Degreed", issue_type="unresolved_identity", severity="high",
                   entity=name or email or f"row {source_row}",
                   detail="Learner matches no Workday worker",
                   action="Row excluded from analytics")
            continue
        if emp_id == "":
            key = email or name
            if key not in reported_out_of_scope:
                reported_out_of_scope.add(key)
                dq.add(source="Degreed", issue_type="out_of_scope_person", severity="medium",
                       entity=name or email, detail=reason or "Not part of the Workday population",
                       action="Row excluded from engagement analytics")
            continue

        status = normalize_learning_status(row["Status"])
        raw_status = clean_text(row["Status"])
        if status is None and raw_status:
            dq.add(source="Degreed", issue_type="unmapped_status", severity="medium",
                   entity=f"{name_by_id.get(emp_id, name)} ({emp_id})",
                   detail=f"Completion status {raw_status!r} is not a known value",
                   action="Status left null")

        completed_on = parse_date(row["Completion Date"])
        if completed_on is None and clean_text(row["Completion Date"]):
            dq.add(source="Degreed", issue_type="unparseable_date", severity="medium",
                   entity=f"{name_by_id.get(emp_id, name)} ({emp_id})",
                   detail=f"Completion date {clean_text(row['Completion Date'])!r} is not a date",
                   action="Treated as missing")

        skill, domain = canonical_skill(row["Skill Tag"])
        raw_skill = clean_text(row["Skill Tag"])
        if skill is None and raw_skill:
            dq.add(source="Degreed", issue_type="unmapped_skill", severity="low",
                   entity=f"{name_by_id.get(emp_id, name)} ({emp_id})",
                   detail=f"Skill tag {raw_skill!r} is not in the alias table",
                   action="Kept verbatim, excluded from skill roll-ups")

        rows.append({
            "employee_id": emp_id,
            "worker_name": name_by_id.get(emp_id, normalize_person_name(name)),
            "learning_item": clean_text(row["Learning Item"]),
            "learning_item_key": _learning_key(row["Learning Item"]),
            "provider": clean_text(row["Provider"]),
            "raw_skill_tag": raw_skill,
            "canonical_skill": skill or raw_skill,
            "skill_domain": domain,
            "status": status,
            "duration_hours": parse_duration_hours(row["Duration (hrs)"]),
            "completed_on": completed_on,
            "assigned_by": clean_text(row["Assigned By"]),
            "source_row": source_row,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Revisions of the same course on the same day are one completion.
    key_cols = ["employee_id", "learning_item_key", "completed_on"]
    dupes = df.duplicated(subset=key_cols, keep="first") & df["completed_on"].notna()
    for _, row in df[dupes].iterrows():
        dq.add(source="Degreed", issue_type="duplicate_completion", severity="medium",
               entity=f"{row['worker_name']} ({row['employee_id']})",
               detail=f"{row['learning_item']!r} already recorded on "
                      f"{row['completed_on'].isoformat()} under another title revision",
               action="Duplicate completion dropped")
    df = df[~dupes].copy()

    df["days_since_completion"] = df["completed_on"].map(
        lambda d: (cfg.AS_OF_DATE - d).days if d else None
    )
    df["is_recent"] = df.apply(
        lambda r: bool(r["status"] == "Completed" and r["days_since_completion"] is not None
                       and r["days_since_completion"] <= cfg.LEARNING_LOOKBACK_DAYS),
        axis=1,
    )
    return df.reset_index(drop=True)


def _learning_key(value: object) -> str | None:
    """Course identity ignoring revision markers and spacing."""
    text = norm_key(value)
    if not text:
        return None
    import re

    text = re.sub(r"\s*\((rev|revision)\.?\s*\d+\)\s*", " ", text)
    return re.sub(r"\s+", " ", text).strip()
