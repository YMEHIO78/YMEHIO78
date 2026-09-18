"""Structural readers for the four raw exports.

These return the source content *verbatim* as strings - no value cleaning. The
only judgement applied here is structural: find the real header row, drop the
title banner and the footer notes, and unpivot the wide matrix. Value-level
repair happens in silver so bronze stays a faithful copy of what arrived.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Rows whose first non-empty cell starts with one of these are report furniture,
# not data: banners, totals, and the notes people leave at the bottom of a sheet.
_FOOTER_PREFIXES = (
    "report effective date", "run by", "total rows", "total voucher budget",
    "total =", "draft - do not circulate", "^^", "notes /", "(doesn't look right",
)


def _as_str_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Everything to string, preserving the original text of each cell."""
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(lambda v: "" if pd.isna(v) else str(v).strip())
    return out


def _drop_furniture(df: pd.DataFrame) -> pd.DataFrame:
    """Drop blank rows and trailing report furniture."""
    def is_furniture(row: pd.Series) -> bool:
        cells = [str(c).strip() for c in row if str(c).strip()]
        if not cells:
            return True
        return cells[0].lower().startswith(_FOOTER_PREFIXES)

    return df[~df.apply(is_furniture, axis=1)].reset_index(drop=True)


def _drop_unnamed(df: pd.DataFrame) -> pd.DataFrame:
    """Remove the phantom columns trailing commas and stray notes create."""
    keep = [
        c for c in df.columns
        if str(c).strip() and not str(c).startswith("Unnamed:")
    ]
    return df[keep]


def read_workday(path: str | Path) -> pd.DataFrame:
    """Workday worker skills extract. Header on row 1, report footer at the end."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    df = _drop_unnamed(df)
    df = _drop_furniture(df)
    df = df[df["Employee ID"].astype(str).str.strip() != ""]
    df.columns = [str(c).strip() for c in df.columns]
    return _as_str_frame(df).reset_index(drop=True)


def read_degreed(path: str | Path, sheet: str = "Report Data") -> pd.DataFrame:
    """Degreed completions. Three banner rows and a blank sit above the header."""
    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    header_idx = _find_header_row(raw, "User Email")
    df = pd.read_excel(path, sheet_name=sheet, header=header_idx, dtype=object)
    df = _drop_unnamed(df)
    df.columns = [str(c).strip() for c in df.columns]
    df = _as_str_frame(df)
    df = _drop_furniture(df)
    df = df[df.apply(lambda r: any(str(c).strip() for c in r), axis=1)]
    return df.reset_index(drop=True)


def read_recert_tracker(path: str | Path, sheet: str = "Tracker") -> pd.DataFrame:
    """Recert tracker. Header on row 1; totals and a draft warning at the bottom."""
    df = pd.read_excel(path, sheet_name=sheet, header=0, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    # Column K holds a reviewer's side comment on one row; keep it as a note.
    stray = [c for c in df.columns if c.startswith("Unnamed:")]
    if stray:
        notes = _as_str_frame(df[stray])
        df["_stray_comment"] = [
            " ".join(v for v in row if v and v.lower() != "nan")
            for row in notes.itertuples(index=False)
        ]
    df = df[[c for c in df.columns if not c.startswith("Unnamed:")]]
    df = _as_str_frame(df)
    df = _drop_furniture(df)
    df = df[df["Engineer"].astype(str).str.strip() != ""]
    return df.reset_index(drop=True)


def read_cert_catalogue(path: str | Path, sheet: str = "Cert List") -> pd.DataFrame:
    """The approved certification list and its list price."""
    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    rows = []
    for _, row in raw.iterrows():
        cells = ["" if pd.isna(v) else str(v).strip() for v in row.tolist()]
        if len(cells) < 3 or not cells[0] or not cells[2]:
            continue
        if cells[0].lower().startswith("approved cert list"):
            continue
        rows.append({"certification": cells[0], "vendor": cells[1], "list_price": cells[2]})
    return pd.DataFrame(rows)


def read_skills_matrix(path: str | Path, sheet: str = "Matrix") -> pd.DataFrame:
    """Unpivot the wide team matrix into one row per person per skill column.

    The sheet carries a two-row banner, a mid-table ``CONTRACTORS / TEMPS``
    divider, and a trailing total. The divider is turned into a
    ``matrix_section`` column so contractors stay identifiable downstream.
    """
    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    header_idx = _find_header_row(raw, "Name")
    header = ["" if pd.isna(v) else str(v).strip() for v in raw.iloc[header_idx].tolist()]

    skill_cols = {
        i: name for i, name in enumerate(header)
        if name and name not in {"Name", "Team", "Notes"} and not name.startswith("Unnamed")
    }
    idx_name = header.index("Name")
    idx_team = header.index("Team") if "Team" in header else None
    idx_notes = header.index("Notes") if "Notes" in header else None

    section = "Employees"
    records: list[dict[str, str]] = []
    for row_num in range(header_idx + 1, len(raw)):
        cells = ["" if pd.isna(v) else str(v).strip() for v in raw.iloc[row_num].tolist()]
        first = cells[idx_name] if idx_name < len(cells) else ""
        if not any(cells):
            continue
        if first.lower().startswith("contractors"):
            section = "Contractors / Temps"
            continue
        if first.lower().startswith("total") or not first:
            continue

        team = cells[idx_team] if idx_team is not None and idx_team < len(cells) else ""
        notes = cells[idx_notes] if idx_notes is not None and idx_notes < len(cells) else ""
        for col_idx, skill in skill_cols.items():
            rating = cells[col_idx] if col_idx < len(cells) else ""
            records.append({
                "matrix_row": str(row_num + 1),
                "matrix_section": section,
                "name": first,
                "team": team,
                "skill": skill,
                "rating": rating,
                "notes": notes,
            })
    return pd.DataFrame(records)


def _find_header_row(raw: pd.DataFrame, anchor: str) -> int:
    """Index of the first row containing ``anchor`` as a cell value."""
    for i in range(len(raw)):
        cells = ["" if pd.isna(v) else str(v).strip() for v in raw.iloc[i].tolist()]
        if anchor in cells:
            return i
    raise ValueError(f"Could not find a header row containing {anchor!r}")
