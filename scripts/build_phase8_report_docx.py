"""Build formatted UIT IS355 Final Report DOCX and export PDF via Word COM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

NAVY = RGBColor(0x0D, 0x17, 0x2C)
ORANGE = RGBColor(0xF4, 0x81, 0x20)
CHARCOAL = RGBColor(0x20, 0x20, 0x20)
MUTED = RGBColor(0x55, 0x5E, 0x6D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT_NAME = "Palatino Linotype"


def _set_cell_shading(cell: Any, fill_hex: str) -> None:
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shd)


def _set_cell_margins(cell: Any, top: int = 80, bottom: int = 80, left: int = 110, right: int = 110) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for side, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def _set_table_borders(table: Any, color_hex: str = "CBD5E1") -> None:
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="6" w:space="0" w:color="{color_hex}"/>'
        f'<w:bottom w:val="single" w:sz="8" w:space="0" w:color="0D172C"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
        f'<w:left w:val="none"/><w:right w:val="none"/><w:insideV w:val="none"/>'
        f"</w:tblBorders>"
    )
    tblPr.append(borders)


def _repeat_header_row(row: Any) -> None:
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:tblHeader"))
    trPr.append(OxmlElement("w:cantSplit"))


def _add_page_field(run: Any, field_name: str) -> None:
    fldChar1 = parse_xml(r'<w:fldChar %s w:fldCharType="begin"/>' % nsdecls("w"))
    instr = parse_xml(r'<w:instrText %s xml:space="preserve"> %s </w:instrText>' % (nsdecls("w"), field_name))
    fldChar2 = parse_xml(r'<w:fldChar %s w:fldCharType="separate"/>' % nsdecls("w"))
    fldChar3 = parse_xml(r'<w:fldChar %s w:fldCharType="end"/>' % nsdecls("w"))
    run._r.append(fldChar1)
    run._r.append(instr)
    run._r.append(fldChar2)
    run._r.append(fldChar3)


def _configure_styles(doc: docx.Document) -> None:
    sec = doc.sections[0]
    sec.page_width = Inches(8.268)
    sec.page_height = Inches(11.693)
    sec.top_margin = Inches(0.75)
    sec.bottom_margin = Inches(0.75)
    sec.left_margin = Inches(0.75)
    sec.right_margin = Inches(0.75)
    sec.different_first_page_header_footer = True

    normal = doc.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = CHARCOAL
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.15

    for lvl, sz, col, sb, sa in (
        (1, 14.0, NAVY, 14, 6),
        (2, 12.0, ORANGE, 11, 4),
        (3, 10.8, NAVY, 8, 3),
    ):
        st = doc.styles[f"Heading {lvl}"]
        st.font.name = FONT_NAME
        st.font.size = Pt(sz)
        st.font.bold = True
        st.font.color.rgb = col
        st.paragraph_format.space_before = Pt(sb)
        st.paragraph_format.space_after = Pt(sa)
        st.paragraph_format.keep_with_next = True

    hdr_p = sec.header.paragraphs[0]
    hdr_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r_h = hdr_p.add_run("X-SPIDE-G · IS355.R11.CTTT.2 Final Project Report · Group 4 – DICTATOR")
    r_h.font.name = FONT_NAME
    r_h.font.size = Pt(8.5)
    r_h.font.color.rgb = MUTED

    ftr_p = sec.footer.paragraphs[0]
    ftr_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = ftr_p.add_run("University of Information Technology – VNU-HCM   |   Page ")
    r1.font.name = FONT_NAME
    r1.font.size = Pt(8.5)
    r1.font.color.rgb = MUTED
    r_pg = ftr_p.add_run()
    r_pg.font.name = FONT_NAME
    r_pg.font.size = Pt(8.5)
    r_pg.font.color.rgb = NAVY
    _add_page_field(r_pg, "PAGE")
    r2 = ftr_p.add_run(" of ")
    r2.font.name = FONT_NAME
    r2.font.size = Pt(8.5)
    r2.font.color.rgb = MUTED
    r_tot = ftr_p.add_run()
    r_tot.font.name = FONT_NAME
    r_tot.font.size = Pt(8.5)
    r_tot.font.color.rgb = NAVY
    _add_page_field(r_tot, "NUMPAGES")


def _p(doc: docx.Document, text: str, *, bold: bool = False, italic: bool = False, size: float | None = None, color: RGBColor | None = None, align: Any = None, space_after: float = 5) -> docx.text.paragraph.Paragraph:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    if align is not None:
        p.alignment = align
    r = p.add_run(text)
    r.font.name = FONT_NAME
    if size is not None:
        r.font.size = Pt(size)
    if bold:
        r.bold = True
    if italic:
        r.italic = True
    if color is not None:
        r.font.color.rgb = color
    return p


def _bullet(doc: docx.Document, lead: str, body: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3.5)
    p.paragraph_format.line_spacing = 1.12
    r1 = p.add_run(lead)
    r1.font.name = FONT_NAME
    r1.bold = True
    r1.font.color.rgb = NAVY
    r2 = p.add_run(body)
    r2.font.name = FONT_NAME
    r2.font.color.rgb = CHARCOAL


def _callout(doc: docx.Document, title: str, body: str, *, fill_hex: str = "F8FAFC", accent_hex: str = "0D172C") -> None:
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.rows[0].cells[0]
    _set_cell_shading(cell, fill_hex)
    _set_cell_margins(cell, top=100, bottom=100, left=140, right=140)
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="24" w:space="0" w:color="{accent_hex}"/>'
        f'<w:top w:val="none"/><w:right w:val="none"/><w:bottom w:val="none"/>'
        f"</w:tcBorders>"
    )
    tcPr.append(borders)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r1 = p.add_run(title + " ")
    r1.font.name = FONT_NAME
    r1.font.size = Pt(10.0)
    r1.bold = True
    r1.font.color.rgb = NAVY
    r2 = p.add_run(body)
    r2.font.name = FONT_NAME
    r2.font.size = Pt(9.8)
    r2.font.color.rgb = CHARCOAL
    doc.add_paragraph().paragraph_format.space_after = Pt(3)


def _table(doc: docx.Document, headers: list[str], rows: list[list[Any]], *, col_widths: list[float] | None = None, font_size: float = 8.6) -> None:
    tbl = doc.add_table(rows=len(rows) + 1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_borders(tbl)

    hdr_row = tbl.rows[0]
    _repeat_header_row(hdr_row)
    for j, h in enumerate(headers):
        cell = hdr_row.cells[j]
        _set_cell_shading(cell, "0D172C")
        _set_cell_margins(cell, top=85, bottom=85, left=80, right=80)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(str(h))
        r.font.name = FONT_NAME
        r.font.size = Pt(font_size)
        r.bold = True
        r.font.color.rgb = WHITE
        if col_widths:
            cell.width = Inches(col_widths[j])

    for i, row_vals in enumerate(rows):
        row = tbl.rows[i + 1]
        trPr = row._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))
        bg = "F8FAFC" if i % 2 == 1 else "FFFFFF"
        for j, val in enumerate(row_vals):
            cell = row.cells[j]
            _set_cell_shading(cell, bg)
            _set_cell_margins(cell, top=65, bottom=65, left=80, right=80)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.08
            r = p.add_run(str(val))
            r.font.name = FONT_NAME
            r.font.size = Pt(font_size)
            r.font.color.rgb = CHARCOAL
            if col_widths:
                cell.width = Inches(col_widths[j])

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(4)


def _figure(doc: docx.Document, img_path: Path, caption: str, *, width_in: float = 6.3) -> None:
    if not img_path.exists():
        raise FileNotFoundError(f"Missing figure: {img_path}")
    p_img = doc.add_paragraph()
    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_img.paragraph_format.keep_with_next = True
    p_img.paragraph_format.space_before = Pt(4)
    p_img.paragraph_format.space_after = Pt(3)
    p_img.add_run().add_picture(str(img_path), width=Inches(width_in))

    p_cap = doc.add_paragraph()
    p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_cap.paragraph_format.space_after = Pt(8)
    rc = p_cap.add_run(caption)
    rc.font.name = FONT_NAME
    rc.font.size = Pt(9.0)
    rc.italic = True
    rc.font.color.rgb = MUTED


def _two_figures(doc: docx.Document, left_img: Path, right_img: Path, caption: str, *, each_width: float = 3.2) -> None:
    tbl = doc.add_table(rows=1, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for idx, pth in enumerate((left_img, right_img)):
        if not pth.exists():
            raise FileNotFoundError(f"Missing figure: {pth}")
        cell = tbl.rows[0].cells[idx]
        _set_cell_margins(cell, top=30, bottom=30, left=40, right=40)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        p.add_run().add_picture(str(pth), width=Inches(each_width))
    p_cap = doc.add_paragraph()
    p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_cap.paragraph_format.space_before = Pt(2)
    p_cap.paragraph_format.space_after = Pt(8)
    rc = p_cap.add_run(caption)
    rc.font.name = FONT_NAME
    rc.font.size = Pt(9.0)
    rc.italic = True
    rc.font.color.rgb = MUTED


def _load_facts() -> dict[str, Any]:
    audit = json.loads((REPO_ROOT / "reports" / "data_audit_summary.json").read_text(encoding="utf-8"))
    e0 = pd.read_csv(REPO_ROOT / "results" / "E0_reproduction.csv").set_index("run_id")
    mc = pd.read_csv(REPO_ROOT / "results" / "model_comparison.csv").set_index("experiment")
    st = pd.read_csv(REPO_ROOT / "results" / "stat_tests.csv")
    sens = pd.read_csv(REPO_ROOT / "results" / "sensitivity_summary.csv")
    e6 = pd.read_csv(REPO_ROOT / "results" / "E6_sanity_check.csv").set_index("metric")
    fx = pd.read_csv(REPO_ROOT / "results" / "feature_extraction_cost.csv").set_index("stage")
    xai = json.loads((REPO_ROOT / "results" / "xai_gsem_summary.json").read_text(encoding="utf-8"))
    err = pd.read_csv(REPO_ROOT / "results" / "error_analysis_cases.csv")
    card = json.loads((REPO_ROOT / "models" / "baseline_v1" / "model_card.json").read_text(encoding="utf-8"))
    e5_gas = pd.read_csv(REPO_ROOT / "results" / "E5_gas.csv")
    e5_sum = json.loads((REPO_ROOT / "results" / "E5_summary.json").read_text(encoding="utf-8"))
    dep = json.loads((REPO_ROOT / "deployments.json").read_text(encoding="utf-8"))
    trace = pd.read_csv(REPO_ROOT / "results" / "traceability_matrix.csv")
    return {
        "audit": audit,
        "e0": e0,
        "mc": mc,
        "st": st,
        "sens": sens,
        "e6": e6,
        "fx": fx,
        "xai": xai,
        "err": err,
        "card": card,
        "e5_gas": e5_gas,
        "e5_sum": e5_sum,
        "dep": dep,
        "trace": trace,
    }


def build_final_report_docx(out_docx: Path, out_pdf: Path | None = None) -> Path:
    facts = _load_facts()
    doc = docx.Document()
    _configure_styles(doc)

    # ---- COVER PAGE ----
    _p(doc, "UNIVERSITY OF INFORMATION TECHNOLOGY – VNU-HCM", bold=True, size=11.5, color=NAVY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
    _p(doc, "FACULTY OF INFORMATION SYSTEMS", bold=True, size=11.0, color=NAVY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
    _p(doc, "IS355 – BLOCKCHAIN TECHNOLOGY", bold=True, size=14.0, color=NAVY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=18)

    _p(doc, "FINAL PROJECT REPORT", bold=True, size=22.0, color=ORANGE, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)
    _p(doc, "End-to-End Implementation, Empirical Evaluation, On-Chain Governance & Defense Package", size=12.0, color=NAVY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)
    _p(
        doc,
        "X-SPIDE-G: Graph-Enhanced Explainable Ponzi Detection and On-Chain Risk Attestation for Ethereum Smart Contracts",
        bold=True,
        size=13.5,
        color=NAVY,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=18,
    )

    _table(
        doc,
        ["Course & Project Metadata", "Details"],
        [
            ["Course / Class", "IS355 – Blockchain Technology · Class IS355.R11.CTTT.2"],
            ["Group", "4 - DICTATOR (5 Members)"],
            ["Repository", "https://github.com/gminh715/IS355_DICTATOR_X-SPIDE-G (Release tag: v1.0-final)"],
            ["Datasets Audited", "X-SPIDE (7,446 contracts / 880 Ponzi), PonziGuard, Blockchain@Unica"],
            ["Live Testnets", "Ethereum Sepolia (chainId 11155111) & Arbitrum Sepolia (chainId 421614)"],
            ["Verification Status", "Vyper 0.4.3 Etherscan v2 Pass - Verified (D1/D2/D3 Sepolia; D1/D3 Arbitrum Sepolia)"],
            ["Duration", "09/2026 – 12/2026 · Ho Chi Minh City, Vietnam"],
        ],
        col_widths=[2.2, 4.56],
        font_size=9.2,
    )

    _table(
        doc,
        ["No.", "Full Name", "Student ID", "Email / Role", "Project Contributions"],
        [
            ["1", "Phạm Vũ Gia Minh", "23520948", "23520948@gm.uit.edu.vn (Leader)", "Architecture freeze, Phase 1 clone audit/splits, Phase 5/7 Vyper & Sepolia E5, Phase 8 synthesis"],
            ["2", "Vũ Thế Vinh", "23521801", "23521801@gm.uit.edu.vn", "Phase 2 X-SPIDE E0–E2 reproduction, in-fold Optuna & RFECV pipeline, baseline_v1 freeze"],
            ["3", "Hoàng Phan Anh Sơn", "23521354", "23521354@gm.uit.edu.vn", "Phase 3 F-BIGRAM / F-GSTAT / F-GSEM bytecode disassembly, CFG builder & extraction benchmark"],
            ["4", "Nguyễn Thiện Nhân", "23521084", "23521084@gm.uit.edu.vn", "Phase 4 25-fold ablations, Nadeau–Bengio & Holm stats, S1–S4 sensitivity, OOF SHAP & error audit"],
            ["5", "Võ Minh Quân", "23521274", "—", "Phase 6 canonical JSON, IPFS CIDv1 + Git mirror, 4-page Streamlit DApp, ethers.js v6 signer, demo"],
        ],
        col_widths=[0.4, 1.35, 0.85, 1.65, 2.51],
        font_size=8.6,
    )

    _p(doc, "Ho Chi Minh City, November 2026", italic=True, size=10.5, color=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
    doc.add_page_break()

    # ---- PAGE 2: EXECUTIVE SUMMARY & ACADEMIC INTEGRITY ----
    doc.add_heading("Executive Summary & Course Deliverables", level=1)
    mc = facts["mc"]
    e0_grid = facts["e0"].loc["E0_random5fold_99feats_gridbest_mean"]
    e5_sum = facts["e5_sum"]
    e5_gas = facts["e5_gas"]
    py_d1 = e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D1") & (e5_gas["operation"] == "finalized_case_total")].iloc[0]
    py_d2 = e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D2") & (e5_gas["operation"] == "finalized_case_total")].iloc[0]
    py_d3_100 = e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D3") & (e5_gas["operation"] == "batch_finalized_total") & (e5_gas["batch_size"] == 100)].iloc[0]
    py_d3_1000 = e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D3") & (e5_gas["operation"] == "batch_finalized_total") & (e5_gas["batch_size"] == 1000)].iloc[0]

    _p(
        doc,
        f"X-SPIDE-G audits and extends the X-SPIDE Ethereum smart Ponzi detection pipeline while anchoring verifiable, "
        f"multi-auditor risk attestations on-chain. After uncovering that 59.09% of Ponzi contracts (520/880) in X-SPIDE belong "
        f"to MinHash near-clone clusters after Solidity CBOR metadata stripping, enforcing leak-free 5x5 StratifiedGroupKFold "
        f"(RQ1) lowers 99-feature LightGBM baseline PR-AUC from {e0_grid['PR-AUC']:.4f} (E0) to {mc.loc['E1','PR_AUC_mean']:.4f} ± {mc.loc['E1','PR_AUC_std']:.4f} "
        f"(E1; Delta = {mc.loc['E1','PR_AUC_mean'] - e0_grid['PR-AUC']:+.4f}, F1: {e0_grid['F1']:.4f} -> {mc.loc['E1','F1_mean']:.4f}). Across our pre-registered RQ2 ablations "
        f"(8-test Holm-Bonferroni family, Nadeau-Bengio df=24, MDE >= 0.02 PR-AUC), explicit opcode bigrams (F-BIGRAM) deliver "
        f"a Confirmed Improvement (+0.0227 PR-AUC to {mc.loc['E4b','PR_AUC_mean']:.4f}, 95% CI [+0.0096, +0.0358], p_Holm = 4.77e-7; "
        f"code-only E3b = {mc.loc['E3b','PR_AUC_mean']:.4f}), whereas 15 basic-block CFG semantic features (F-GSEM, E4c = {mc.loc['E4c','PR_AUC_mean']:.4f}, "
        f"Delta = +0.0058, 95% CI [-0.0037, +0.0152]) yield No Significant Difference and are transparently reported as a negative structural result.",
    )
    _p(
        doc,
        f"On the blockchain layer (RQ3 / E5), three verified Vyper 0.4.3 contracts (D1 full storage, D2 compact event-only, "
        f"D3 Merkle-batch) enforce k-of-n quorum separation and append-only evidence anchoring. On deterministic Cancun EVM, "
        f"a single finalized D1 case consumes {int(py_d1['gas_used']):,} gas (FAIL vs <= 250,000 ceiling; ${py_d1['mainnet_ref_cost_usd']:.6f} "
        f"at 0.084427 gwei / ETH = $1,900.68), D2 reduces gas by 31.06% to {int(py_d2['gas_used']):,}, and D3 amortizes gas to "
        f"{py_d3_100['gas_per_case']:.2f} gas/case at N=100 and {py_d3_1000['gas_per_case']:.2f} gas/case at N=1,000 (PASS vs <= 10,000 target). "
        f"Live confirmation latency meets the <= 2-block target on Sepolia (median {e5_sum['latency_summary']['sepolia']['median_blocks']:.2f} block / "
        f"{e5_sum['latency_summary']['sepolia']['median_seconds']:.3f}s) and achieves {e5_sum['latency_summary']['arbitrum-sepolia']['median_seconds']:.3f}s "
        f"median finality on Arbitrum Sepolia, alongside live Sepolia T1/T6/T8 security proofs and a 4-page DApp with zero-server-key MetaMask signing.",
    )

    _callout(
        doc,
        "Academic Integrity & Pre-Registration Disclosure:",
        "All hypotheses, MDE thresholds (>= 0.02 PR-AUC), Holm-Bonferroni families, and on-chain gas/latency pass criteria were frozen in docs/preregistration.md prior to Phase 4/7 execution. Null results (F-GSEM E4c/E4d; S3 missing block_number; Risk R6 PonziGuard downgrade; D1 exceeding the 250k gas ceiling) and testnet limitations (EOA owner_type='eoa_demo_limit', zero-L1-fee testnet receipts, EIP-8037 Sepolia state repricing) are reported verbatim without post-hoc threshold edits.",
        fill_hex="FFF7ED",
        accent_hex="F48120",
    )

    # ---- SECTION 1 ----
    doc.add_heading("1. Introduction & Research Questions (RQ1–RQ3)", level=1)
    _p(
        doc,
        "Smart Ponzi schemes deployed on Ethereum promise unsustainable returns funded exclusively by subsequent investors "
        "while masquerading as high-yield DeFi, staking, or gaming contracts. Although machine learning detectors trained on "
        "account transaction statistics and bytecode opcode frequencies achieve high headline scores on random splits [1, 5], "
        "two real-world barriers impede trustworthy deployment: (1) near-identical contract clone families leak across train/test splits "
        "and static unigram opcode histograms discard control-flow context, and (2) off-chain ML verdicts lack cryptographic immutability, "
        "neutral quorum governance, and tamper-evident model/explanation provenance when published to ecosystems or auditors.",
    )
    _table(
        doc,
        ["RQ", "Research Question", "Primary Hypotheses & Quantitative Benchmarks"],
        [
            ["RQ1", "How faithfully does X-SPIDE [1] reproduce on raw random splits (E0), and what performance degradation occurs once CBOR-stripped exact & near-clone groups are quarantined across folds (E1, E2)?", "Reproduce X-SPIDE [1] 47/99-feature LightGBM on S_full random splits, then measure Delta PR-AUC / F1 on S_code 5x5 StratifiedGroupKFold(group_near) and test in-fold RFECV (E2)."],
            ["RQ2", "Do bytecode transition statistics (F-GSTAT), ordered opcode bigrams (F-BIGRAM), and basic-block CFG semantic features (F-GSEM) yield >= 0.02 PR-AUC gain over E1 without transaction leakage?", "Pre-registered 8-test Holm-Bonferroni family with Nadeau-Bengio paired t-tests (df=24), S1/S2/S4 sensitivity checks, external E6 sanity check, global/local SHAP, and 24-case error analysis."],
            ["RQ3", "Can canonical SHAP-backed ML risk evidence be anchored to an immutable k-of-n Vyper registry with deterministic 1-byte tamper rejection, bounded gas, and <= 2-block confirmation?", "Benchmark D1/D2/D3 gas on Cancun PyEVM (<= 250k single, <= 10k amortized), Sepolia & Arbitrum Sepolia latency (n=30 each, <= 2 L1 blocks), T1-T12 invariants, and client-side ethers.js v6 signing."],
        ],
        col_widths=[0.6, 3.1, 3.06],
    )

    # ---- SECTION 2 ----
    doc.add_heading("2. Literature Review & Research Gaps (G1, G2)", level=1)
    _p(
        doc,
        "Ethereum Ponzi detection spans three main methodological branches alongside a distinct smart-contract provenance literature:",
    )
    _bullet(doc, "Account + Unigram Opcode Tabular Branch [1, 5, 6]: ", "Chen et al. [5] combined transaction-history summaries with unigram opcode frequencies, while Pennella et al. (X-SPIDE [1], [9]) refined a 99-feature LightGBM + SHAP pipeline (23 account features + 76 normalized opcodes). However, random 85/15 or 5-fold splits allow factory-cloned Ponzi bytecodes to appear in both training and test partitions.")
    _bullet(doc, "Ordered Opcode N-Gram & Sequence Branch [5, 7]: ", "Prior bytecode-analysis work showed that short ordered mnemonic sequences (bigrams/n-grams) capture dispatcher patterns, CALLVALUE guards, and storage-write idioms lost by flat bag-of-opcodes vectors. Crucially, recent static graph papers rarely benchmark CFG features head-to-head against explicit in-fold top-K opcode bigrams under identical clone-grouped splits.")
    _bullet(doc, "Control-Flow & Runtime Behavior Graph Branch [2, 3, 8]: ", "SADPonzi [8] extracted semantic-aware symbolic control-flow paths, and PonziGuard / Liang et al. [2, 3, 10] introduced Contract Runtime Behavior Graphs (CRBGs) executed dynamically. Purely static CFG recovery from deployed EVM bytecode faces indirect JUMP/JUMPI targets stored on stack/memory, motivating rigorous measurement of both unresolved jump rates and marginal value over opcode bigrams.")
    _bullet(doc, "On-Chain AI Audit Provenance [4]: ", "ProvAuditChain [4] anchors AI-driven audit metadata via content hashes + IPFS URIs. However, most provenance designs either rely on a single trusted publisher or store heavyweight mutable metadata off-chain without explicit multi-auditor k-of-n quorum transitions.")
    _table(
        doc,
        ["Gap / Innovation", "Identified Limitation in Literature", "X-SPIDE-G Solution (I1, I2)"],
        [
            ["G1 / I1 (Methodological + Structural ML)", "Random splits leak exact/near-clone contracts; black-box or unigram bytecode models lack head-to-head comparison against ordered opcode bigrams & CFG semantics under strict anti-leakage CV.", "Quarantine clones via CBOR stripping + MinHash (group_near, 5x5 grouped CV); benchmark F-GSTAT (16), F-BIGRAM (in-fold top-200), and F-GSEM (15 CFG/SCC/PageRank) with pre-registered Holm-adjusted Nadeau-Bengio stats."],
            ["G2 / I2 (Blockchain Governance & Evidence)", "ML risk scores lack deterministic canonicalization, tamper detection, and neutral multi-auditor finality without custodial server keys.", "Schema v1.0 canonical JSON (6-decimal fixed strings, sorted UTF-8) + IPFS CIDv1/Git mirror + Vyper 0.4.3 k-of-n registry (D1/D2/D3) + zero-server-key ethers.js v6 MetaMask signer."],
        ],
        col_widths=[1.4, 2.5, 2.86],
    )

    # ---- SECTION 3 ----
    doc.add_heading("3. Threat Model & \"Why Blockchain?\"", level=1)
    _p(
        doc,
        "Per docs/threat_model.md, our system separates four explicit actors: (1) Owner (governance multisig on production/Sepolia; manages authorized auditor roster and threshold k, prohibited from registering cases or attesting), (2) Auditors (k-of-n security analysts operating independent wallets who register canonical cases and submit Approve/Reject/NeedsReview attestations), (3) ML Service / DApp Operator (untrusted off-chain inference & packaging node; possesses zero private keys for live networks), and (4) Public Verifiers (any ecosystem participant recomputing keccak256 over fetched evidence JSON and calling view verify_evidence).",
    )
    _table(
        doc,
        ["Adversarial Threat Scenario", "Signed Off-Chain DB Only", "X-SPIDE-G Blockchain Registry (D1/D2/D3)", "Verified By"],
        [
            ["1. Owner / DB admin alters past score or deletes evidence", "Vulnerable (DB admin controls keys/logs)", "Mitigated: zero modify/delete functions; owner cannot attest", "T6 (local + Sepolia)"],
            ["2. Operator backdates a detection timestamp after an exploit", "Vulnerable unless external TSA used", "Mitigated: block.timestamp anchored in immutable Case/Event", "D1/D2/D3 state"],
            ["3. Silent 1-byte tampering of SHAP rationale JSON", "Detected only per-sig; easy re-signing", "Mitigated: verify_evidence(case_id, keccak256) returns False", "T8 + Phase 6"],
            ["4. Single compromised auditor pushes false Ponzi label", "Single key can publish unilateral verdict", "Mitigated: k-of-n quorum (threshold=2) required for Approved", "T4, T11 fuzz"],
            ["5. Model weight mismatch behind reported risk score", "Opaque model version string", "Mitigated: model_version_hash immutable on-chain per case", "Schema v1.0"],
            ["6. Auditor edits vote secretly without audit trail", "Silent overwrite in SQL row", "Mitigated: revision++ & append-only Attested/StatusChanged logs", "T5, T9 events"],
            ["7. Server host compromise steals live auditor private keys", "Key theft if server holds signing keys", "Mitigated: live signing exclusively via client MetaMask signer", "Phase 6 security"],
            ["8. Off-chain JSON host drops availability", "Single server failure", "Hybrid mitigation: IPFS CIDv1 (ipfs://bafkrei...) + Git mirror", "Sec 5.5 + Verifier"],
        ],
        col_widths=[1.85, 1.5, 2.41, 1.0],
        font_size=8.3,
    )
    _p(
        doc,
        "Explicit Non-Goals & Scope Limits: On-chain contracts intentionally do NOT execute LightGBM inference in the EVM, store unbounded JSON payloads on-chain, enforce fraud finality in court, guarantee global censorship resistance without third-party IPFS pinning, or eliminate single-owner admin risk when deployed via a testnet EOA (documented transparently in deployments.json as owner_type='eoa_demo_limit').",
    )

    # ---- SECTION 4 ----
    doc.add_heading("4. Data Audit, Clone Clustering & Anti-Leakage Splits", level=1)
    audit = facts["audit"]
    ce = audit["clones_exact"]
    cn = audit["clones_near"]
    pg = audit["overlap"]["ponziguard"]
    ks_rows = [
        [
            r["feature"],
            f"{int(r['n_kept']):,}",
            f"{int(r['n_excluded']):,}",
            f"{r['median_kept']:.3g}",
            f"{r['median_excluded']:.3g}",
            f"{r['ks_stat']:.4f}",
            f"{r['p_value']:.2e}",
        ]
        for r in audit["ks_8k_kept_vs_dropped"]
    ]
    _p(
        doc,
        f"Phase 1 audited X-SPIDE commit {audit['xspide_commit'][:12]} alongside PonziGuard [10] and Blockchain@Unica [11]. "
        f"Both DS_deployed_bytecode.csv and DS_full_bytecode.csv contain 7,446 unique valid contracts (880 Ponzi, 6,566 non-Ponzi, 0 label conflicts). "
        f"Deployed runtime hex achieves 100.0% coverage (|S_code| = |S_full| = 7,446; zero 0x/missing rows), clearing Risk R1 (> 400 Ponzi). "
        f"Comparing 7,446 kept contracts against 516 contracts excluded from bytecode_opcode_8k.csv (7,962 rows) reveals statistically significant "
        f"distribution shifts (Risk R2), e.g., lifetime median 15.0 vs 2.0 days (KS = 0.1384, p = 1.58e-8) and tx_out median 0.0 vs 1.0 (KS = 0.2467, p = 2.50e-26).",
    )
    _table(
        doc,
        ["KS Test Feature (8k Kept vs Excluded)", "n_kept", "n_excl", "Median Kept", "Median Excl", "KS Stat", "p-value"],
        ks_rows,
        col_widths=[2.0, 0.7, 0.7, 0.9, 0.9, 0.75, 0.81],
    )
    _p(
        doc,
        f"Bytecode Normalization & Clone Clustering: Stripping Solidity CBOR compiler metadata [13] trimmed {audit['metadata_counts']['true']['total']:,} "
        f"contracts (595 Ponzi / 5,822 non-Ponzi), leaving {audit['metadata_counts']['false']['total']:,} pre-0.4.7 bytecodes without CBOR trailers. "
        f"Exact SHA-256 clustering produced {ce['total_groups']:,} groups (max size {ce['max_size']}, {ce['mixed_label_groups_count']} mixed-label groups), "
        f"putting {ce['ponzi_in_multi']}/{ce['total_ponzi']} ({ce['ponzi_in_multi_pct']:.2f}%) Ponzi contracts in multi-member clusters. MinHash LSH "
        f"clustering on normalized 5-gram opcodes (threshold t=0.80, 128 permutations) collapsed the corpus to {cn['total_groups']:,} near-clone groups "
        f"(max size {cn['max_size']}, {cn['mixed_label_groups_count']} mixed-label clusters), exposing that {cn['ponzi_in_multi']}/{cn['total_ponzi']} "
        f"({cn['ponzi_in_multi_pct']:.2f}%) of Ponzi contracts and {cn['non_ponzi_in_multi_pct']:.2f}% of non-Ponzi contracts share near-duplicate code.",
    )
    _p(
        doc,
        f"Cross-Dataset Overlap & Frozen Splits: Blockchain@Unica overlaps X-SPIDE on 161/182 unique addresses (plus 3 exact code-hash / 4 near-clone overlaps among live disjoint checks). "
        f"PonziGuard's .bin corpus has 78/89 extracted Ponzi runtimes overlapping X-SPIDE by near-clone group, leaving only {pg['ponzi_bins']['remaining_unique_hashes']} unique non-overlapping Ponzi "
        f"bytecodes (+ {pg['non_ponzi_bins']['remaining_unique_hashes']} non-Ponzi = 107). Per pre-registered Risk R6 (< 30 independent Ponzis), E6 was formally downgraded to SANITY_CHECK_ONLY. "
        f"Finally, 55 immutable split JSONs were frozen (25 S_code_group_near, 25 S_code_group_exact for S1, 5 S_full_E0_random). Temporal holdout S3 could not be generated because block_number is absent in X-SPIDE and BigQuery credentials are unavailable locally.",
    )

    # ---- SECTION 5 ----
    doc.add_heading("5. Methodology", level=1)
    doc.add_heading("5.1 Bytecode Feature Families & Runtime Extraction Cost", level=2)
    fx = facts["fx"]
    _p(
        doc,
        "In addition to the 99 X-SPIDE baseline features (23 account stats + 76 row-wise relative opcode frequencies), Phase 3 implemented linear-sweep EVM disassembly on CBOR-stripped runtime bytecode (normalized opcode families grouping PUSH1..32 -> PUSH, DUP1..16 -> DUP, SWAP1..16 -> SWAP, LOG0..4 -> LOG):",
    )
    _bullet(doc, "F-BIGRAM (In-Fold Top-200): ", "Normalized consecutive opcode pairs computed per contract and vectorized strictly inside each training fold via BigramTopKVectorizer(top_k=200), preventing test vocabulary leakage.")
    _bullet(doc, "F-GSTAT (16 Transition Statistics): ", "Directed normalized opcode multigraph descriptors: node/edge counts, density, reciprocity, average out/in degree & weighted strengths, degree entropy, top-1 out/in concentration, normalized self-loop ratio, and size-normalized /L ratios.")
    _bullet(doc, "F-GSEM (15 Basic-Block CFG & Semantic Descriptors): ", "Static basic-block CFG recovering JUMP/JUMPI targets via local stack-push tracking: n_blocks, n_cfg_edges, cyclomatic complexity, n_scc_cycles, has_loop_with_call, n_loops_with_call, n_loops_with_sstore, path_callvalue_to_call, n_blocks_with_call, call_block_ratio, unresolved_jump_ratio, has_selfdestruct, selfdestruct_reachable, and personalized opcode PageRank weights pagerank_CALL & pagerank_SSTORE.")

    fx_rows = [
        [
            stg,
            f"{int(fx.loc[stg, 'n_contracts']):,}",
            f"{int(fx.loc[stg, 'n_errors'])} ({fx.loc[stg, 'error_rate_pct']:.1f}%)",
            f"{fx.loc[stg, 'median_ms']:.3f} ms",
            f"{fx.loc[stg, 'p95_ms']:.3f} ms",
            f"{fx.loc[stg, 'total_s']:.2f} s",
        ]
        for stg in ("disasm", "bigram", "gstat", "gsem", "end_to_end")
    ]
    _table(
        doc,
        ["Extraction Stage", "Contracts", "Errors", "Median / Contract", "p95 / Contract", "Total Corpus Time"],
        fx_rows,
        col_widths=[1.35, 0.9, 0.9, 1.25, 1.15, 1.21],
    )
    _p(
        doc,
        f"Benchmark hardware: {fx.loc['end_to_end', 'cpu_info']}, {fx.loc['end_to_end', 'ram_gb']:.2f} GB RAM, Python {fx.loc['end_to_end', 'python_version']}. Zero failures occurred across all 7,446 contracts (16.584 ms median end-to-end; 554 truncated-PUSH contracts handled deterministically).",
    )

    doc.add_heading("5.2 Anti-Leakage ML Pipeline & Statistical Protocol", level=2)
    _p(
        doc,
        "Every 5x5 experiment reuses the identical 25 frozen StratifiedGroupKFold(n_splits=5) partitions on group_near (seeds 42..46). Inside each outer training fold, Optuna executes 30 TPE trials using 3-fold inner StratifiedGroupKFold (optimizing PR-AUC) with strictly nested feature selection (RFECV in E2; BigramTopKVectorizer in E3b/E4b/E4d), selects threshold tau* maximizing OOF F1, and evaluates once on the untouched outer fold. Statistical inference uses Nadeau-Bengio corrected paired t-tests (rho = 1/(k+1) or empirical n_te/(n_tr+n_te), df = 24), two-sided Wilcoxon signed-rank checks, and Holm-Bonferroni correction across the pre-registered 8-test family, declaring 'Confirmed Improvement' only when Delta PR-AUC >= 0.02, 95% NB CI lies strictly above 0, and p_Holm < 0.05.",
    )

    doc.add_heading("5.3 Smart Contract Architecture & Canonical Evidence Pipeline", level=2)
    dep = facts["dep"]["networks"]
    _p(
        doc,
        "Three Vyper 0.4.3 contracts share identical k-of-n governance (default k=2 of n=3 auditors; owner cannot act as auditor or alter/delete records): D1 RiskAttestationRegistry (full Case + Attestation structs), D2_EventOnly (minimal CompactCase + event payloads), and D3_MerkleBatch (OpenZeppelin-compatible sorted-pair keccak256 Merkle root batching). Phase 6 implements deterministic canonical JSON serialization (sorted UTF-8 keys, 6-decimal fixed string floats, shap_digest + keccak256 evidence_hash + ABI-encoded case_id), IPFS CIDv1 raw-block generation with Git mirror persistence (evidence/<case_id>.json), a 4-page Streamlit DApp, and a zero-server-key ethers.js v6 MetaMask signer.",
    )
    _table(
        doc,
        ["Network (Chain ID)", "Variant", "Contract Address", "Verification Status", "Role Setup"],
        [
            ["Sepolia (11155111)", "D1", dep["sepolia"]["contracts"]["D1"]["address"], "Pass - Verified", "3 auditors, k=2, owner=eoa_demo_limit"],
            ["Sepolia (11155111)", "D2", dep["sepolia"]["contracts"]["D2"]["address"], "Pass - Verified", "3 auditors, k=2, owner=eoa_demo_limit"],
            ["Sepolia (11155111)", "D3", dep["sepolia"]["contracts"]["D3"]["address"], "Pass - Verified", "3 auditors, k=2, owner=eoa_demo_limit"],
            ["Arbitrum Sepolia (421614)", "D1", dep["arbitrum-sepolia"]["contracts"]["D1"]["address"], "Pass - Verified", "3 auditors, k=2, owner=eoa_demo_limit"],
            ["Arbitrum Sepolia (421614)", "D3", dep["arbitrum-sepolia"]["contracts"]["D3"]["address"], "Pass - Verified", "3 auditors, k=2, owner=eoa_demo_limit"],
            ["Anvil PyEVM (31337)", "D1/D2/D3", f"{dep['anvil']['contracts']['D1']['address'][:14]}... / D2 / D3", "Local dev RPC", "Anvil test auditors #1-#3, k=2"],
        ],
        col_widths=[1.45, 0.65, 2.35, 1.05, 1.26],
        font_size=8.4,
    )

    # ---- SECTION 6 ----
    doc.add_heading("6. Experimental Results", level=1)
    doc.add_heading("6.1 RQ1: Baseline Reproduction & Clone-Leakage Quantification (E0–E2)", level=2)
    e0 = facts["e0"]
    card = facts["card"]
    e0_pub = e0.loc["published_xspide_paper"]
    e0_1009 = e0.loc["E0_1009_47feats_unbal"]
    e0_43 = e0.loc["E0_2710_43feats"]
    e0_5f = e0.loc["E0_random5fold_99feats_gridbest_mean"]
    _table(
        doc,
        ["Run / Configuration", "Split Scheme", "Feats", "PR-AUC", "ROC-AUC", "F1", "P", "R", "Accuracy"],
        [
            ["Published X-SPIDE [1]", "Paper 85/15 random", "47", "—", f"{e0_pub['ROC-AUC']:.4f}", f"{e0_pub['F1']:.4f}", f"{e0_pub['P']:.4f}", f"{e0_pub['R']:.4f}", f"{e0_pub['Accuracy']:.4f}"],
            ["E0 (47-feat notebook)", "Random 85/15 (seed 42)", "47", f"{e0_1009['PR-AUC']:.4f}", f"{e0_1009['ROC-AUC']:.4f}", f"{e0_1009['F1']:.4f}", f"{e0_1009['P']:.4f}", f"{e0_1009['R']:.4f}", f"{e0_1009['Accuracy']:.4f}"],
            ["E0 (43-feat notebook)", "Random 85/15 (seed 42)", "43", f"{e0_43['PR-AUC']:.4f}", f"{e0_43['ROC-AUC']:.4f}", f"{e0_43['F1']:.4f}", f"{e0_43['P']:.4f}", f"{e0_43['R']:.4f}", f"{e0_43['Accuracy']:.4f}"],
            ["E0 Random 5-fold (GridBest)", "S_full random 5-fold", "99", f"{e0_5f['PR-AUC']:.4f}", f"{e0_5f['ROC-AUC']:.4f}", f"{e0_5f['F1']:.4f}", f"{e0_5f['P']:.4f}", f"{e0_5f['R']:.4f}", f"{e0_5f['Accuracy']:.4f}"],
            ["E1 Main Grouped Baseline", "S_code 5x5 group_near", "99", f"{mc.loc['E1','PR_AUC_mean']:.4f} ± {mc.loc['E1','PR_AUC_std']:.4f}", f"{mc.loc['E1','ROC_AUC_mean']:.4f}", f"{mc.loc['E1','F1_mean']:.4f} ± {mc.loc['E1','F1_std']:.4f}", f"{mc.loc['E1','P_mean']:.4f}", f"{mc.loc['E1','R_mean']:.4f}", f"{mc.loc['E1','Accuracy_mean']:.4f}"],
            ["E2 In-Fold RFECV", "S_code 5x5 group_near", str(mc.loc['E2', 'n_features']), f"{mc.loc['E2','PR_AUC_mean']:.4f} ± {mc.loc['E2','PR_AUC_std']:.4f}", f"{mc.loc['E2','ROC_AUC_mean']:.4f}", f"{mc.loc['E2','F1_mean']:.4f} ± {mc.loc['E2','F1_std']:.4f}", f"{mc.loc['E2','P_mean']:.4f}", f"{mc.loc['E2','R_mean']:.4f}", f"{mc.loc['E2','Accuracy_mean']:.4f}"],
        ],
        col_widths=[1.55, 1.25, 0.65, 0.92, 0.56, 0.86, 0.48, 0.49, 0.50],
        font_size=8.0,
    )
    _p(
        doc,
        f"Quarantining near-clones (E0 random -> E1 group_near) cuts PR-AUC by {mc.loc['E1','PR_AUC_mean'] - e0_5f['PR-AUC']:+.4f} and F1 by {mc.loc['E1','F1_mean'] - e0_5f['F1']:+.4f}, confirming substantial clone-leakage optimism in ungrouped splits. Because |S_code| == |S_full| (100% coverage), E1-full matches E1 in population and verifies exact pipeline alignment (0.8767). In-fold RFE (E2) prunes to 71.4 ± 16.7 features with zero meaningful gain (Delta PR-AUC = +0.00003, p_Holm = 1.0). Frozen models/baseline_v1 (seed 42 fold 0, tau* = {card['classification_threshold']:.6f}) achieves PR-AUC = {card['demo_fold_metrics']['pr_auc']:.4f} and F1 = {card['demo_fold_metrics']['f1']:.4f}.",
    )

    doc.add_heading("6.2 RQ2: Feature Engineering Ablations, Statistics, Sensitivity & XAI", level=2)
    exp_rows = []
    for eid in ("E1", "E2", "E3", "E3b", "E3c", "E4", "E4b", "E4c", "E4d"):
        r = mc.loc[eid]
        exp_rows.append([
            eid,
            str(r["feature_set"]),
            str(r["n_features"]),
            f"{r['PR_AUC_mean']:.4f} ± {r['PR_AUC_std']:.4f}",
            f"{r['Delta_PR_AUC_vs_E1']:+.4f}",
            f"{r['F1_mean']:.4f} ± {r['F1_std']:.4f}",
            f"{r['ROC_AUC_mean']:.4f}",
            f"{r['Recall_at_P90_mean']:.4f}",
        ])
    _table(
        doc,
        ["Exp", "Feature Set", "Feats", "PR-AUC (mean ± std)", "Delta PR-AUC", "F1 (mean ± std)", "ROC-AUC", "Recall@P>=0.9"],
        exp_rows,
        col_widths=[0.42, 1.88, 0.55, 1.08, 0.72, 0.98, 0.55, 0.58],
        font_size=8.1,
    )

    st_prereg = facts["st"][facts["st"]["test_suite"] == "preregistered_holm_8"]
    st_rows = [
        [
            r["comparison"],
            f"{r['mean_delta']:+.4f}",
            f"[{r['ci95_low']:+.4f}, {r['ci95_high']:+.4f}]",
            f"{r['nb_t_stat']:+.2f}",
            f"{r['nb_p_value']:.2e}",
            f"{r['p_holm']:.2e}",
            r["conclusion"],
        ]
        for _, r in st_prereg.iterrows()
    ]
    _table(
        doc,
        ["Comparison (df=24)", "Delta PR-AUC", "95% Nadeau-Bengio CI", "t-stat", "NB p-val", "p_Holm", "Pre-Registered Verdict"],
        st_rows,
        col_widths=[1.15, 0.75, 1.35, 0.55, 0.72, 0.72, 1.52],
        font_size=8.1,
    )

    _two_figures(
        doc,
        REPO_ROOT / "figures" / "pr_curves.png",
        REPO_ROOT / "figures" / "delta_pr_auc_ci.png",
        "Figure 1. Left: Out-of-fold Precision-Recall curves across E1–E4d (seed 42). Right: Paired Nadeau-Bengio 95% confidence intervals vs pre-registered MDE = +0.02 PR-AUC.",
    )

    sens_rows = []
    for _, sr in facts["sens"].iterrows():
        v_pr = "N/A" if pd.isna(sr["variant_PR_AUC_mean"]) else f"{sr['variant_PR_AUC_mean']:.4f}"
        d_pr = "N/A" if pd.isna(sr["Delta_PR_AUC"]) else f"{sr['Delta_PR_AUC']:+.4f}"
        d_f1 = "N/A" if pd.isna(sr["Delta_F1"]) else f"{sr['Delta_F1']:+.4f}"
        variant_str = "N/A" if pd.isna(sr["variant"]) else str(sr["variant"])
        sens_rows.append([sr["study"], variant_str, str(sr["paired_same_splits"]), v_pr, d_pr, d_f1, sr["notes"]])
    _table(
        doc,
        ["Sensitivity", "Variant", "Paired", "PR-AUC", "Delta PR-AUC", "Delta F1", "Methodology Notes"],
        sens_rows,
        col_widths=[1.05, 1.15, 0.45, 0.60, 0.72, 0.62, 2.17],
        font_size=7.9,
    )

    e6 = facts["e6"]
    _p(
        doc,
        f"Sensitivity & External Sanity Check (S1–S4, E6): S1 demonstrates that weaker exact-clone grouping (group_exact) inflates PR-AUC by +0.0283 on E1 (0.9051 vs 0.8767) and +0.0272 on E4c (0.9097 vs 0.8825), proving that MinHash near-clone grouping prevents substantial residual leakage. Both S2 (CBOR removal/recomputation, max |Delta| = 0.0028) and S4 (raw vs normalized mnemonics, max |Delta| = 0.0025) confirm result stability. Under Risk R6, the code-only external E6 check on 107 non-overlapping PonziGuard bytecodes (10 Ponzi / 97 non-Ponzi) reaches PR-AUC = {e6.loc['pr_auc', 'point']:.4f} (95% bootstrap CI [{e6.loc['pr_auc', 'ci95_low']:.4f}, {e6.loc['pr_auc', 'ci95_high']:.4f}]) and F1 = {e6.loc['f1', 'point']:.4f} (TP=6, FP=2, TN=95, FN=4).",
    )

    xai = facts["xai"]
    err = facts["err"]
    _p(
        doc,
        f"Explainability & Error Analysis: Out-of-fold TreeExplainer rankings on seed-42 E4c identify call_block_ratio (mean |SHAP| = 0.2833, Spearman r = +0.874), n_loops_with_call (0.2061; E[SHAP | >0] = +1.052 vs -0.114), n_blocks_with_call (0.1707), and unresolved_jump_ratio (0.1520, Spearman r = -0.897) among top F-GSEM attributions, passing our domain sanity check (has_loop_with_call mean SHAP = +0.3191 when present vs -0.0305 when absent). Across 7,446 contracts, 526 (7.06%) exceed unresolved_jump_ratio > 0.50 (below the 50% Risk R4 threshold). Seed-42 E4c produces TP={xai['total_tp_seed42']}, FP={xai['total_fp_seed42']}, TN={xai['total_tn_seed42']}, FN={xai['total_fn_seed42']}; inspecting top-12 FP + top-12 FN highest-margin failures shows FPs concentrate in benign payout/distributor loops (e.g. xspide_02699) and mixed-label near-clone clusters ({xai['fp_mixed_cluster_count']} FPs, {xai['fn_mixed_cluster_count']} FNs overall), while FNs lack static loop+CALL motifs.",
    )
    _two_figures(
        doc,
        REPO_ROOT / "figures" / "shap_beeswarm_E4c.png",
        REPO_ROOT / "figures" / "shap_gsem_importance.png",
        "Figure 2. Left: Seed-42 OOF SHAP beeswarm for E4c (99 + F-GSEM). Right: F-GSEM global feature attribution ranking.",
    )
    _two_figures(
        doc,
        REPO_ROOT / "figures" / "cfg_tp.png",
        REPO_ROOT / "figures" / "shap_waterfall_tp.png",
        "Figure 3. Case study TP contract (xspide_02792, P=0.9999995): Basic-Block CFG with call-in-loop SCC (left) and TreeExplainer SHAP waterfall (right).",
    )
    _two_figures(
        doc,
        REPO_ROOT / "figures" / "cfg_fp.png",
        REPO_ROOT / "figures" / "cfg_fn.png",
        "Figure 4. Structural failure archetypes: False Positive benign payout loop (xspide_06872, left) vs False Negative acyclic dispatcher (xspide_04097, right).",
    )

    doc.add_heading("6.3 RQ3: On-Chain Gas, Cost, Latency, Security & Live DApp (E5)", level=2)
    def _usd(gas: float, gwei: float, eth_usd: float = 1900.68) -> float:
        return gas * gwei * 1e-9 * eth_usd

    sep_deploy = int(float(e5_gas[(e5_gas["network"] == "sepolia") & (e5_gas["variant"] == "D1") & (e5_gas["operation"] == "deploy")].iloc[0]["gas_used"]))
    sep_d1 = int(float(e5_gas[(e5_gas["network"] == "sepolia") & (e5_gas["variant"] == "D1") & (e5_gas["operation"] == "finalized_case_total")].iloc[0]["gas_used"]))
    sep_d2 = int(float(e5_gas[(e5_gas["network"] == "sepolia") & (e5_gas["variant"] == "D2") & (e5_gas["operation"] == "finalized_case_total")].iloc[0]["gas_used"]))
    sep_d3_100 = float(e5_gas[(e5_gas["network"] == "sepolia") & (e5_gas["variant"] == "D3") & (e5_gas["operation"] == "batch_finalized_total")].iloc[0]["gas_per_case"])
    py_rm = int(float(e5_gas[(e5_gas["network"] == "anvil_pyevm") & (e5_gas["variant"] == "D1") & (e5_gas["operation"] == "remove_auditor")].iloc[0]["gas_used"]))

    _table(
        doc,
        ["Variant & Operation", "Cancun PyEVM Gas", "Sepolia Live (EIP-8037)", "Mainnet Ref ($ @ 0.0844 gwei)", "Stress ($ @ 30 gwei)", "Pre-Reg Target Verdict"],
        [
            ["D1 deploy (constructor)", "1,068,183", f"{sep_deploy:,}", f"${_usd(1068183, 0.084427):.6f}", f"${_usd(1068183, 30):.2f}", "One-time deployment"],
            ["D1 register_case + 2x attest (k=2)", f"{int(py_d1['gas_used']):,}", f"{sep_d1:,} (spot)", f"${py_d1['mainnet_ref_cost_usd']:.6f}", f"${_usd(float(py_d1['gas_used']), 30):.2f}", "FAIL (> 250,000 limit)"],
            ["D1 remove_auditor (warm)", f"{py_rm:,}", "—", "$0.005222", f"${_usd(py_rm, 30):.2f}", "Governance revocation"],
            ["D2 EventOnly finalized (k=2)", f"{int(py_d2['gas_used']):,}", f"{sep_d2:,} (spot)", f"${py_d2['mainnet_ref_cost_usd']:.6f}", f"${_usd(float(py_d2['gas_used']), 30):.2f}", "-31.06% vs D1 (FAIL > 250k)"],
            ["D3 MerkleBatch (N=100, /case)", f"{py_d3_100['gas_per_case']:.2f}", f"{sep_d3_100:,.2f} (spot)", f"${py_d3_100['mainnet_ref_cost_per_case_usd']:.6f}", f"${_usd(float(py_d3_100['gas_per_case']), 30):.4f}", "PASS (<= 10,000 target)"],
            ["D3 MerkleBatch (N=1,000, /case)", f"{py_d3_1000['gas_per_case']:.2f}", "—", f"${py_d3_1000['mainnet_ref_cost_per_case_usd']:.6f}", f"${_usd(float(py_d3_1000['gas_per_case']), 30):.5f}", "PASS (<= 10,000 target)"],
        ],
        col_widths=[1.75, 0.95, 1.05, 1.05, 0.85, 1.11],
        font_size=8.0,
    )
    lat_sep = e5_sum["latency_summary"]["sepolia"]
    lat_arb = e5_sum["latency_summary"]["arbitrum-sepolia"]
    sec_sep = e5_sum["live_networks"]["sepolia"]["security_on_main_d1"]
    t8_sep = e5_sum["live_networks"]["sepolia"]["T8_sepolia_verify_evidence"]
    _p(
        doc,
        f"Gas, Fee & Latency Findings: Cancun PyEVM results reveal a critical negative cost result: storing the 10-field Case struct plus two cold attestations costs {int(py_d1['gas_used']):,} gas in D1, exceeding the pre-registered 250,000-gas single-case threshold by 70.98%. D2 trims 31.06% ({int(py_d2['gas_used']):,} gas), while D3 Merkle batching achieves O(1) batch gas (~357,453 total regardless of N), driving amortized cost down to {py_d3_100['gas_per_case']:.2f} gas/case at N=100 (PASS <= 10k) and 357.46 gas/case at N=1,000. Note that Sepolia's Glamsterdam/EIP-8037 state-creation repricing raises live state-write gas (~7.37M deploy, 693,762 register_case), while Arbitrum Sepolia receipts reflect $0.016278 for D1 and $0.000136/case for D3 (reference-only due to gasUsedForL1 = 0x0 on testnet). Across n=30 sequential attestations per testnet, Sepolia confirms in median {lat_sep['median_blocks']:.2f} block / {lat_sep['median_seconds']:.3f}s (p95 = {lat_sep['p95_seconds']:.3f}s, PASS <= 2 blocks) and Arbitrum Sepolia confirms in {lat_arb['median_seconds']:.3f}s (p95 = {lat_arb['p95_seconds']:.3f}s). Live Sepolia receipts confirm T1/T6 reverts (all 5 status=0, e.g., owner attest tx {sec_sep['T6_owner_attest_revert']['tx_hash'][:14]}..., main D1 state untouched) and T8 tamper rejection ({t8_sep['verify_exact_onchain']} vs {t8_sep['verify_tampered_onchain']}). Qualitative architecture comparison against ProvAuditChain [4] shows X-SPIDE-G uniquely contributes Vyper k-of-n quorum separation, EIP-170 modular batching, and client-side zero-server-key signing.",
    )
    _figure(
        doc,
        REPO_ROOT / "figures" / "gas_vs_batch.png",
        "Figure 5. Gas per case across D1, D2, and D3 (N = 1..1,000) vs pre-registered ceilings (Cancun PyEVM), plus Sepolia vs Arbitrum Sepolia 30-tx confirmation latency.",
        width_in=6.2,
    )
    _two_figures(
        doc,
        REPO_ROOT / "demo" / "screenshots" / "02_page1_shap_cfg.png",
        REPO_ROOT / "demo" / "screenshots" / "08_page4_verified_events.png",
        "Figure 6. Live X-SPIDE-G DApp (xspide_00439, score = 0.998390): Page 1 SHAP + CFG analysis (left) and Page 4 on-chain ✅ VERIFIED + append-only event audit (right).",
    )
    _two_figures(
        doc,
        REPO_ROOT / "demo" / "screenshots" / "09_page4_tampered_reject.png",
        REPO_ROOT / "demo" / "screenshots" / "10_signer_metamask.png",
        "Figure 7. Page 4 1-byte tamper rejection ❌ verify_evidence == False (left) and zero-server-key client-side ethers.js v6 + MetaMask signer pre-filled URL (right).",
    )

    # ---- SECTION 7 ----
    doc.add_heading("7. Discussion: Negative Results & Threats to Validity", level=1)
    doc.add_heading("7.1 Why F-GSEM Underperformed F-BIGRAM & Why D1 Exceeded 250k Gas", level=2)
    _bullet(doc, "Negative ML Structural Result (F-GSEM vs F-BIGRAM): ", "Despite strong domain intuition (call_block_ratio and loop-with-CALL SHAP ranking), adding 15 scalar CFG features to E1 (+0.0058 PR-AUC) or E4b (+0.0016) failed to pass MDE or statistical significance, whereas sparse in-fold top-200 opcode bigrams (F-BIGRAM) yielded a Confirmed +0.0227 PR-AUC gain (and code-only E3b reached 0.9013). Two concrete mechanisms explain this: (a) Solidity 0.4–0.5 runtime code resolves dynamic function dispatchers and loop exit addresses via stack/memory pointers, leaving median 19.18% (and 526 contracts > 50%) unresolved indirect jumps that fragment loop back-edges, and (b) opcode bigrams directly preserve local micro-idioms (e.g., CALLVALUE->ISZERO->JUMPI, SLOAD->CALL) without suffering from indirect jump loss.")
    _bullet(doc, "Negative On-Chain Cost Result (D1 Single-Case Gas = 427,461 > 250,000): ", "Storing full 10-field structs plus per-auditor mappings incurs three separate cold SSTORE trees across register_case and two cold attest calls. Rather than relaxing thresholds post-hoc, E5 transparently flags D1 FAIL against the 250k ceiling and validates D3_MerkleBatch as the production scaling path (3,574.53 gas/case at N=100, 357.46 at N=1,000).")

    doc.add_heading("7.2 Threats to Validity", level=2)
    _bullet(doc, "Internal & Label Validity: ", "X-SPIDE exhibits 10 exact-clone and 24 near-clone clusters containing conflicting Ponzi/non-Ponzi labels, contributing to 14 FPs and 38 FNs in seed-42 E4c. Without source-verified manual relabeling, this represents an upper bound on label cleanliness.")
    _bullet(doc, "Construct Validity (Static Disassembly & Testnet Accounting): ", "Linear-sweep stack tracking misses dynamic memory/storage jump targets (7.06% contracts > 50% unresolved jumps) and skips symbolic execution. On-chain, Sepolia EIP-8037 repricing differs from Cancun, and Arbitrum Sepolia returns gasUsedForL1 = 0x0.")
    _bullet(doc, "External & Temporal Validity: ", "X-SPIDE lacks block_number (preventing S3 temporal holdout), leaving post-2023 Solidity proxy/diamond Ponzi patterns untested; additionally, bytecode_opcode_8k.csv exclusion introduces statistically significant selection bias (Risk R2), and E6 only has 10 independent non-overlapping Ponzis (Risk R6).")

    # ---- SECTION 8 ----
    doc.add_heading("8. Limitations & Future Work", level=1)
    _bullet(doc, "Safe Multisig Governance & L2 Anchoring: ", "Migrate owner from testnet eoa_demo_limit to a 2-of-3 Gnosis Safe on Sepolia/Arbitrum One and route high-volume detection batches exclusively through D3_MerkleBatch.")
    _bullet(doc, "Symbolic CFG Lifting & Temporal Benchmarks: ", "Replace stack-local jump resolution with abstract interpretation / Gigahorse/Vandal-style EVM IR decompilation and collect timestamped post-2024 contracts to execute S3 temporal splits.")
    _bullet(doc, "Managed IPFS Pinning & Threshold Signatures: ", "Attach authenticated Pinata/Web3.Storage pinning webhooks alongside Git mirrors, and evaluate off-chain EIP-712 multisig aggregation to compress k attest transactions into a single D1/D3 verification call.")

    # ---- SECTION 9 ----
    doc.add_heading("9. Unified References & Traceability Appendix", level=1)
    refs = [
        "[1] L. Pennella, F. Pinelli, and L. Galletta, “X-SPIDE: An eXplainable Machine Learning Pipeline for Detecting Smart Ponzi Contracts in Ethereum,” IEEE Access, vol. 13, pp. 85037–85055, 2025. https://doi.org/10.1109/ACCESS.2025.3569565",
        "[2] R. Liang, J. Chen, C. Wu et al., “Towards Effective Detection of Ponzi Schemes on Ethereum with Contract Runtime Behavior Graph,” ACM Trans. Softw. Eng. Methodol., vol. 34, no. 4, Art. 106, 2025. https://doi.org/10.1145/3707458",
        "[3] R. Liang, J. Chen, K. He et al., “PonziGuard: Detecting Ponzi Schemes on Ethereum with Contract Runtime Behavior Graph (CRBG),” in Proc. ICSE, 2024, Art. 64, pp. 1–12. https://doi.org/10.1145/3597503.3623318",
        "[4] G. C. Akor, L. A. C. Ahakonye, J. M. Lee, and D.-S. Kim, “ProvAuditChain: A Gas-Efficient On-Chain Provenance Framework for AI-Driven Smart Contract Audits,” in Proc. ICTC, 2025, pp. 1155–1157.",
        "[5] W. Chen, Z. Zheng, J. Cui, E. C.-H. Ngai, P. Zheng, and Y. Zhou, “Detecting Ponzi Schemes on Ethereum: Towards Healthier Blockchain Technology,” in Proc. WWW, 2018, pp. 1409–1418. https://doi.org/10.1145/3178876.3186046",
        "[6] M. Bartoletti, S. M. Carta, T. Cimoli, and R. Saia, “Dissecting Ponzi schemes on Ethereum: Identification, analysis, and impact,” Future Gener. Comput. Syst., vol. 102, pp. 259–277, 2020.",
        "[7] S. Fan, S. Fu, H. Xu, and C. Zhu, “Expose Your Mask: Smart Ponzi Schemes Detection on Blockchain,” in Proc. IJCNN, 2020, pp. 1–7.",
        "[8] W. Chen, X. Li, Y. Sui, N. He, H. Wang, L. Wu, and X. Luo, “SADPonzi: Detecting and Characterizing Ponzi Schemes in Ethereum Smart Contracts,” Proc. ACM Meas. Anal. Comput. Syst., vol. 5, no. 2, Art. 14, Jun. 2021.",
        "[9] L. Pennella, “X-SPIDE Official Source Code and Dataset,” GitHub, 2025. https://github.com/LucaPennella/x-spide-smart-ponzi-detection",
        "[10] R. Liang et al., “PonziGuard Dataset and Tools,” GitHub. https://github.com/PonziDetection/PonziGuard/tree/main/dataset",
        "[11] Blockchain@Unica, “Ethereum Ponzi Address List,” GitHub. https://github.com/blockchain-unica/ethereum-ponzi/blob/master/ponzi-addresses.csv",
        "[12] scikit-learn developers, “StratifiedGroupKFold.” https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html",
        "[13] Solidity developers, “Contract Metadata.” https://docs.soliditylang.org/en/latest/metadata.html",
    ]
    for r in refs:
        p = _p(doc, r, size=9.0, space_after=2.5)
        p.paragraph_format.left_indent = Inches(0.28)
        p.paragraph_format.first_line_indent = Inches(-0.28)

    doc.add_page_break()
    doc.add_heading("Appendix A: Complete Metric-to-Artifact Traceability Matrix", level=1)
    _p(
        doc,
        "Generated directly from results/traceability_matrix.csv by scripts/build_phase8_traceability.py. Every quantitative figure in Sections 4–7 links deterministically to its source data file, script, split configuration, and Git commit.",
        size=9.2,
    )
    t_rows = [
        [
            r["metric_id"],
            r["metric_name"],
            r["reported_value"],
            f"{r['source_file']} ({r['generating_script']})",
            r["git_commit"],
        ]
        for _, r in facts["trace"].iterrows()
    ]
    _table(
        doc,
        ["ID", "Metric / Claim", "Reported Value", "Source File & Script", "Commit"],
        t_rows,
        col_widths=[0.85, 1.45, 2.25, 1.65, 0.56],
        font_size=7.2,
    )

    out_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_docx))
    print(f"Saved Word report: {out_docx} ({out_docx.stat().st_size:,} bytes)")

    if out_pdf is not None:
        import win32com.client as wc

        word = wc.DispatchEx("Word.Application")
        word.Visible = False
        try:
            wdoc = word.Documents.Open(str(out_docx.resolve()), ReadOnly=True)
            wdoc.SaveAs2(str(out_pdf.resolve()), FileFormat=17)
            wdoc.Close(False)
        finally:
            word.Quit()
        print(f"Exported PDF report: {out_pdf} ({out_pdf.stat().st_size:,} bytes)")
    return out_docx


def main() -> None:
    build_final_report_docx(
        REPO_ROOT / "4_DICTATOR_IS355_Final_Report.docx",
        REPO_ROOT / "4_DICTATOR_IS355_Final_Report.pdf",
    )


if __name__ == "__main__":
    main()
