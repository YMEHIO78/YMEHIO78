"""Loaders for the maintained reference tables under ``data/reference``.

Everything that encodes a human judgement - which spellings are the same skill,
which people are the same person, what an "H" rating means - lives in CSV so it
can be reviewed and edited without touching pipeline code.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .normalize import norm_key, normalize_person_name

# Code/src/skills_analysis/reference.py -> repo root is four levels up.
REFERENCE_DIR = Path(__file__).resolve().parents[3] / "Data" / "reference"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


@dataclass(frozen=True)
class SkillAlias:
    canonical_skill: str
    skill_domain: str
    notes: str


@dataclass(frozen=True)
class ProficiencyMapping:
    proficiency: int | None
    confidence: str
    notes: str


@lru_cache(maxsize=None)
def skill_aliases(reference_dir: str | None = None) -> dict[str, SkillAlias]:
    rows = _read(Path(reference_dir or REFERENCE_DIR) / "skill_aliases.csv")
    return {
        norm_key(r["raw_skill"]): SkillAlias(
            canonical_skill=r["canonical_skill"],
            skill_domain=r["skill_domain"],
            notes=r["notes"],
        )
        for r in rows
        if r["raw_skill"]
    }


@lru_cache(maxsize=None)
def proficiency_scale(reference_dir: str | None = None) -> dict[str, ProficiencyMapping]:
    rows = _read(Path(reference_dir or REFERENCE_DIR) / "proficiency_scale.csv")
    return {
        norm_key(r["raw_value"]): ProficiencyMapping(
            proficiency=int(r["proficiency"]) if r["proficiency"] else None,
            confidence=r["confidence"],
            notes=r["notes"],
        )
        for r in rows
        if r["raw_value"]
    }


@lru_cache(maxsize=None)
def identity_overrides(reference_dir: str | None = None) -> dict[tuple[str, str], str]:
    """(source_system, normalised source key) -> employee_id.

    An empty employee_id means the key was reviewed and is deliberately out of
    scope (external partner, another org). Those are kept as empty strings so
    the pipeline can tell "known but excluded" from "never seen".
    """
    rows = _read(Path(reference_dir or REFERENCE_DIR) / "identity_overrides.csv")
    return {
        (r["source_system"].lower(), norm_key(r["source_key"])): r["employee_id"]
        for r in rows
        if r["source_key"]
    }


@lru_cache(maxsize=None)
def identity_reasons(reference_dir: str | None = None) -> dict[tuple[str, str], str]:
    rows = _read(Path(reference_dir or REFERENCE_DIR) / "identity_overrides.csv")
    return {
        (r["source_system"].lower(), norm_key(r["source_key"])): r["resolution_reason"]
        for r in rows
        if r["source_key"]
    }


@lru_cache(maxsize=None)
def critical_skills(reference_dir: str | None = None) -> dict[str, bool]:
    rows = _read(Path(reference_dir or REFERENCE_DIR) / "critical_skills.csv")
    return {r["canonical_skill"]: r["is_critical"].lower() == "true" for r in rows if r["canonical_skill"]}


@lru_cache(maxsize=None)
def critical_skill_rationale(reference_dir: str | None = None) -> dict[str, str]:
    rows = _read(Path(reference_dir or REFERENCE_DIR) / "critical_skills.csv")
    return {r["canonical_skill"]: r["rationale"] for r in rows if r["canonical_skill"]}


@lru_cache(maxsize=None)
def identity_name_index(reference_dir: str | None = None) -> dict[tuple[str, str], str]:
    """(source_system, name in ``First Last`` order) -> employee_id.

    The same person is written ``Chen, Wei-Lin`` in one row and ``Wei-Lin Chen``
    in the next, so every override key is also indexed by its normalised name
    order. Only unambiguous names are indexed: if two people in a system would
    normalise to the same name, neither is.
    """
    rows = _read(Path(reference_dir or REFERENCE_DIR) / "identity_overrides.csv")
    candidates: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        if not r["source_key"]:
            continue
        name = normalize_person_name(r["source_key"])
        if not name or "@" in r["source_key"] or "\\" in r["source_key"]:
            continue
        key = (r["source_system"].lower(), norm_key(name))
        candidates.setdefault(key, set()).add(r["employee_id"])
    return {k: next(iter(v)) for k, v in candidates.items() if len(v) == 1}
