#!/usr/bin/env python3
"""Run the full pipeline locally and write the outputs to ``build/``.

Same modules the Databricks notebooks import, so what you see here is what the
lakehouse tables will contain. Useful for iterating on cleaning rules without a
cluster, and for regenerating the findings in ``docs/FINDINGS.md``.

    python local/run_analysis.py [--out build]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]      # Code/
REPO_ROOT = CODE_ROOT.parent                          # repository root
sys.path.insert(0, str(CODE_ROOT / "src"))

import pandas as pd  # noqa: E402

from skills_analysis import config as cfg, extract, gold, report, transform  # noqa: E402

RAW = REPO_ROOT / "Data" / "raw"


def run(out_dir: Path) -> dict[str, pd.DataFrame]:
    dq = transform.DQLog()

    bronze = {
        "workday_worker_skills": extract.read_workday(RAW / "workday_worker_skills_20260901.csv"),
        "degreed_completions": extract.read_degreed(RAW / "degreed_learning_completions_20260901.xlsx"),
        "recert_tracker": extract.read_recert_tracker(RAW / "recert_tracker_draft.xlsx"),
        "cert_catalogue": extract.read_cert_catalogue(RAW / "recert_tracker_draft.xlsx"),
        "skills_matrix": extract.read_skills_matrix(RAW / "skills_matrix_final_v3_1.xlsx"),
    }

    workers = transform.build_worker_dim(bronze["workday_worker_skills"], dq)
    worker_skills = transform.build_worker_skills(bronze["workday_worker_skills"], workers, dq)
    matrix = transform.build_matrix_ratings(bronze["skills_matrix"], dq)
    certs_silver = transform.build_certifications(
        bronze["recert_tracker"], bronze["cert_catalogue"], workers, dq
    )
    learning = transform.build_learning(bronze["degreed_completions"], workers, dq)

    profile = gold.build_worker_skill_profile(worker_skills, matrix, workers)
    coverage = gold.build_skill_coverage(profile, workers)
    certs = gold.build_cert_compliance(certs_silver, workers)
    scorecard = gold.build_org_scorecard(workers, profile, learning, certs)
    kpis = gold.build_kpi_snapshot(workers, profile, coverage, learning, certs)
    dq_frame = dq.frame()
    dq_summary = gold.build_data_quality_summary(dq_frame)

    tables = {
        **{f"bronze_{k}": v for k, v in bronze.items()},
        "silver_worker": workers,
        "silver_worker_skill": worker_skills,
        "silver_matrix_rating": matrix,
        "silver_certification": certs_silver,
        "silver_learning_completion": learning,
        "silver_data_quality_issue": dq_frame,
        "gold_worker_skill_profile": profile,
        "gold_skill_coverage": coverage,
        "gold_cert_compliance": certs,
        "gold_org_scorecard": scorecard,
        "gold_kpi_snapshot": kpis,
        "gold_data_quality_summary": dq_summary,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_csv(out_dir / f"{name}.csv", index=False)
    # The report is a deliverable, not a build artefact: it is written to
    # Deliverables/ and committed, while the intermediate tables stay in build/.
    deliverable = REPO_ROOT / "Deliverables" / "skills_report.html"
    deliverable.parent.mkdir(parents=True, exist_ok=True)
    deliverable.write_text(report.build_report(tables), encoding="utf-8")
    return tables


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(CODE_ROOT / "build"),
                        help="directory for the intermediate CSV tables")
    args = parser.parse_args()

    tables = run(Path(args.out))
    print(f"As-of date: {cfg.AS_OF_DATE}\n")
    for name, frame in tables.items():
        print(f"  {name:36s} {len(frame):5d} rows")
    print(f"\nWrote {len(tables)} tables to {args.out}")
    print(f"Wrote Deliverables/skills_report.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
