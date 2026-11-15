"""Automated exit-gate tests for Phase 8 deliverables, artifacts, video duration, and secret hygiene."""

from __future__ import annotations

import csv
from pathlib import Path
import re
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_phase8_reproducibility_files_exist() -> None:
    for rel in (
        "requirements.txt",
        "pyproject.toml",
        "Makefile",
        "scripts/run_all.py",
        "scripts/build_phase8_traceability.py",
        "scripts/build_phase8_report_docx.py",
        "scripts/build_phase8_slides_and_video.py",
        "README.md",
    ):
        path = REPO_ROOT / rel
        assert path.exists() and path.stat().st_size > 0, f"Missing or empty reproducibility file: {rel}"

    req_text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("lightgbm==", "py-evm==", "web3==", "eth-tester==", "python-docx==", "python-pptx==", "shap=="):
        assert pkg in req_text, f"Pinned package missing from requirements.txt: {pkg}"
    assert 'sys_platform == "win32"' in req_text

    mk = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("verify:", "clean-clone-e1:", "test:", "phase8-trace:"):
        assert target in mk


def test_phase8_traceability_matrix_complete() -> None:
    csv_path = REPO_ROOT / "results" / "traceability_matrix.csv"
    md_path = REPO_ROOT / "reports" / "traceability_matrix.md"
    assert csv_path.exists() and md_path.exists()

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 35, f"Expected >= 35 traceability entries, found {len(rows)}"
    ids = {r["metric_id"] for r in rows}
    for required_id in ("DATA-01", "DATA-04", "RQ1-02", "RQ1-03", "RQ2-E4b", "STAT-E4b_vs_E1", "RQ3-01", "RQ3-03", "RQ3-04", "RQ3-05"):
        assert required_id in ids, f"Missing required metric ID: {required_id}"

    # Every listed source artifact must exist cleanly in repo
    for row in rows:
        for rel in row["source_file"].split(";"):
            rel_clean = rel.strip()
            assert (REPO_ROOT / rel_clean).exists(), f"Traceability source missing: {rel_clean}"


def test_phase8_final_report_outputs() -> None:
    md = REPO_ROOT / "reports" / "final_report.md"
    paper_pdf = REPO_ROOT / "paper" / "main.pdf"
    for p in (md, paper_pdf):
        assert p.exists() and p.stat().st_size > 10_000, f"Final report artifact incomplete: {p}"

    md_text = md.read_text(encoding="utf-8")
    for required_section in (
        "1. Introduction",
        "2. Literature Review",
        "3. Threat Model",
        "4. Data Audit",
        "5. Methodology",
        "6. Experimental Results",
        "7. Discussion: Negative Results",
        "8. Limitations & Future Work",
        "9. Unified References",
    ):
        assert required_section in md_text, f"Missing section in final_report.md: {required_section}"
    assert "[13]" in md_text

    # Non-empty IEEE paper PDF page count check (>= 8 pages)
    pdf_bytes = paper_pdf.read_bytes()
    pages = re.findall(rb"/Type\s*/Page(?!s)\b", pdf_bytes)
    assert len(pages) >= 8, f"Expected multi-page IEEE paper PDF, found {len(pages)}"


def test_phase8_demo_video_and_screenshots() -> None:
    mp4 = REPO_ROOT / "demo" / "X-SPIDE-G_demo.mp4"
    script_md = REPO_ROOT / "reports" / "demo_script.md"
    assert mp4.exists() and mp4.stat().st_size > 1_000_000
    assert script_md.exists() and "xspide_00439" in script_md.read_text(encoding="utf-8")

    screenshots = sorted((REPO_ROOT / "demo" / "screenshots").glob("*.png"))
    assert len(screenshots) >= 10

    if sys.platform == "win32":
        ps = (
            "$sh = New-Object -ComObject Shell.Application; "
            f"$f = $sh.Namespace('{(REPO_ROOT / 'demo').resolve()}'); "
            "$i = $f.ParseName('X-SPIDE-G_demo.mp4'); "
            "Write-Output $f.GetDetailsOf($i, 27)"
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=True)
        hh, mm, ss = (int(part) for part in res.stdout.strip().split(":"))
        dur_sec = hh * 3600 + mm * 60 + ss
        assert 180 <= dur_sec <= 300, f"Demo video duration must be 180..300s (3-5 min), got {dur_sec}s"


def test_phase8_defense_qa_covers_all_appendix_d_questions() -> None:
    qa = (REPO_ROOT / "reports" / "defense_qa.md").read_text(encoding="utf-8")
    for q_header in ("### Q1.", "### Q2.", "### Q3.", "### Q4.", "### Q5.", "### Q6.", "### Q7.", "### Q8."):
        assert q_header in qa, f"Missing Appendix D defense question {q_header}"
    for metric_ref in ("STAT-E4b_vs_E1", "RQ1-03", "DATA-01", "RQ3-05", "EVD-01"):
        assert metric_ref in qa, f"Missing traceability citation {metric_ref} in defense_qa.md"


def test_no_secrets_committed_or_staged_in_text_files() -> None:
    env_file = REPO_ROOT / ".env"
    env_example = REPO_ROOT / ".env.example"
    assert env_example.exists()
    secret_patterns = [
        re.compile(r"ETHERSCAN_API_KEY\s*=\s*[A-Za-z0-9]{12,}"),
        re.compile(r"ALCHEMY_API_KEY\s*=\s*[A-Za-z0-9_-]{12,}"),
        re.compile(r"PRIVATE_KEY\s*=\s*0x[0-9a-fA-F]{64}"),
    ]
    # Hardcoded public Anvil test accounts in test/demo scripts are allowed only in known Anvil fixtures;
    # ensure no live env secrets appear in source/report/script files.
    scan_roots = [REPO_ROOT / "scripts", REPO_ROOT / "src", REPO_ROOT / "app", REPO_ROOT / "reports", REPO_ROOT / "docs"]
    for root in scan_roots:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".html", ".csv"}:
                content = p.read_text(encoding="utf-8", errors="ignore")
                for pat in secret_patterns:
                    assert not pat.search(content), f"Potential secret pattern matched in {p}: {pat.pattern}"
    if env_file.exists():
        # Confirm .env itself is gitignored
        chk = subprocess.run(["git", "check-ignore", ".env"], cwd=REPO_ROOT, capture_output=True, text=True)
        assert chk.returncode == 0, ".env must remain gitignored"
