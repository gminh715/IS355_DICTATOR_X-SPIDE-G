"""Build Phase 8.3 Final Presentation (PPTX + PDF) and 3-5 min Demo Video (MP4)."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_STORYBOARD = REPO_ROOT / "demo" / "_video_storyboard.pptx"

NAVY = RGBColor(0x0D, 0x17, 0x2C)
DARK_SLATE = RGBColor(0x1E, 0x29, 0x3B)
ORANGE = RGBColor(0xF4, 0x81, 0x20)
BLUE_ACCENT = RGBColor(0x25, 0x63, 0xEB)
GREEN = RGBColor(0x15, 0x80, 0x3D)
RED = RGBColor(0xB9, 0x1C, 0x1C)
LIGHT_BG = RGBColor(0xF8, 0xFA, 0xFC)
BORDER = RGBColor(0xCB, 0xD5, 0xE1)
CHARCOAL = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x47, 0x55, 0x69)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
SOFT_ORANGE = RGBColor(0xFF, 0xF7, 0xED)
SOFT_BLUE = RGBColor(0xEF, 0xF6, 0xFF)
SOFT_GREEN = RGBColor(0xF0, 0xFD, 0xF4)
SOFT_RED = RGBColor(0xFE, 0xF2, 0xF2)

FONT_HEAD = "Segoe UI"
FONT_BODY = "Segoe UI"
FONT_MONO = "Consolas"


def _blank_prs() -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs


def _add_rect(
    slide: Any,
    left: float,
    top: float,
    width: float,
    height: float,
    fill: RGBColor,
    line_color: RGBColor | None = None,
    line_pt: float = 1.0,
    rounded: bool = False,
) -> Any:
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, Inches(left), Inches(top), Inches(width), Inches(height))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line_color is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line_color
        shp.line.width = Pt(line_pt)
    if rounded:
        shp.adjustments[0] = 0.04
    return shp


def _add_text(
    slide: Any,
    left: float,
    top: float,
    width: float,
    height: float,
    text: str,
    *,
    font_size: float = 13.0,
    bold: bool = False,
    color: RGBColor = CHARCOAL,
    font_name: str = FONT_BODY,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    valign: MSO_ANCHOR = MSO_ANCHOR.TOP,
) -> Any:
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = valign
    tf.margin_left = Inches(0.06)
    tf.margin_right = Inches(0.06)
    tf.margin_top = Inches(0.03)
    tf.margin_bottom = Inches(0.03)
    for idx, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(2)
        run = p.add_run()
        run.text = line
        run.font.name = font_name
        run.font.size = Pt(font_size)
        run.font.bold = bold
        run.font.color.rgb = color
    return tb


def _add_bullets(
    slide: Any,
    left: float,
    top: float,
    width: float,
    height: float,
    items: list[tuple[str, str]],
    *,
    font_size: float = 12.0,
    space_after: float = 5.0,
) -> Any:
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.06)
    tf.margin_right = Inches(0.06)
    tf.margin_top = Inches(0.03)
    tf.margin_bottom = Inches(0.03)
    for idx, (lead, body) in enumerate(items):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        r0 = p.add_run()
        r0.text = f"▪ {lead}: " if lead else "▪ "
        r0.font.name = FONT_BODY
        r0.font.size = Pt(font_size)
        r0.font.bold = True
        r0.font.color.rgb = NAVY
        r1 = p.add_run()
        r1.text = body
        r1.font.name = FONT_BODY
        r1.font.size = Pt(font_size)
        r1.font.color.rgb = CHARCOAL
    return tb


def _add_card(
    slide: Any,
    left: float,
    top: float,
    width: float,
    height: float,
    title: str,
    body_items: list[tuple[str, str]],
    *,
    fill: RGBColor = WHITE,
    border: RGBColor = BORDER,
    accent: RGBColor = NAVY,
    font_size: float = 11.5,
) -> None:
    _add_rect(slide, left, top, width, height, fill, line_color=border, line_pt=1.0, rounded=True)
    _add_rect(slide, left + 0.02, top + 0.02, width - 0.04, 0.34, accent)
    _add_text(
        slide,
        left + 0.1,
        top + 0.04,
        width - 0.2,
        0.30,
        title,
        font_size=12.0,
        bold=True,
        color=WHITE,
    )
    _add_bullets(slide, left + 0.1, top + 0.42, width - 0.2, height - 0.48, body_items, font_size=font_size, space_after=4.0)


def _add_table(
    slide: Any,
    left: float,
    top: float,
    width: float,
    height: float,
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[float] | None = None,
    font_size: float = 10.0,
) -> Any:
    tbl_shape = slide.shapes.add_table(len(rows) + 1, len(headers), Inches(left), Inches(top), Inches(width), Inches(height))
    tbl = tbl_shape.table
    if col_widths:
        for i, w in enumerate(col_widths):
            tbl.columns[i].width = Inches(w)

    def _style_cell(cell: Any, text: str, bg: RGBColor, fg: RGBColor, bold: bool = False, align: PP_ALIGN = PP_ALIGN.LEFT) -> None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = bg
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = Inches(0.06)
        cell.margin_right = Inches(0.06)
        cell.margin_top = Inches(0.03)
        cell.margin_bottom = Inches(0.03)
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = str(text)
        run.font.name = FONT_BODY
        run.font.size = Pt(font_size)
        run.font.bold = bold
        run.font.color.rgb = fg

    for c_idx, h in enumerate(headers):
        _style_cell(tbl.cell(0, c_idx), h, NAVY, WHITE, bold=True)
    for r_idx, row in enumerate(rows):
        bg = LIGHT_BG if r_idx % 2 else WHITE
        for c_idx, val in enumerate(row):
            s = str(val)
            fg = CHARCOAL
            bold = False
            if "FAIL" in s or "TAMPERED" in s:
                fg = RED
                bold = True
            elif "PASS" in s or "Confirmed Improvement" in s or "VERIFIED" in s:
                fg = GREEN
                bold = True
            _style_cell(tbl.cell(r_idx + 1, c_idx), s, bg, fg, bold=bold)
    return tbl_shape


def _add_picture_fit(slide: Any, img_path: Path, left: float, top: float, max_w: float, max_h: float, border: bool = True) -> None:
    with Image.open(img_path) as im:
        px_w, px_h = im.size
    ratio = min(max_w / px_w, max_h / px_h)
    w = px_w * ratio
    h = px_h * ratio
    x = left + (max_w - w) / 2.0
    y = top + (max_h - h) / 2.0
    if border:
        _add_rect(slide, x - 0.02, y - 0.02, w + 0.04, h + 0.04, WHITE, line_color=BORDER, line_pt=1.0)
    slide.shapes.add_picture(str(img_path), Inches(x), Inches(y), width=Inches(w), height=Inches(h))


def _header_footer(slide: Any, title: str, subtitle: str, page_no: int, total_pages: int = 14) -> None:
    _add_rect(slide, 0, 0, 13.333, 7.5, LIGHT_BG)
    _add_rect(slide, 0, 0, 13.333, 0.92, NAVY)
    _add_rect(slide, 0, 0.92, 13.333, 0.05, ORANGE)
    _add_text(slide, 0.45, 0.10, 11.4, 0.44, title, font_size=21.0, bold=True, color=WHITE, font_name=FONT_HEAD)
    _add_text(slide, 0.45, 0.54, 11.4, 0.32, subtitle, font_size=11.5, bold=False, color=RGBColor(0xCB, 0xD5, 0xE1))
    _add_rect(slide, 0, 7.16, 13.333, 0.34, NAVY)
    _add_text(
        slide,
        0.45,
        7.20,
        9.5,
        0.24,
        "UIT VNU-HCM · IS355.R11.CTTT.2 · Group 4 – DICTATOR · X-SPIDE-G (v1.0-final)",
        font_size=9.5,
        color=RGBColor(0xCB, 0xD5, 0xE1),
    )
    _add_text(
        slide,
        11.5,
        7.20,
        1.4,
        0.24,
        f"Slide {page_no} / {total_pages}",
        font_size=9.5,
        bold=True,
        color=ORANGE,
        align=PP_ALIGN.RIGHT,
    )


def _new_slide(prs: Presentation) -> Any:
    return prs.slides.add_slide(prs.slide_layouts[6])


def _load_facts() -> dict[str, Any]:
    dep = json.loads((REPO_ROOT / "deployments.json").read_text(encoding="utf-8"))
    e5 = json.loads((REPO_ROOT / "results" / "E5_summary.json").read_text(encoding="utf-8"))
    return {"dep": dep, "e5": e5}


def build_presentation(out_pptx: Path, out_pdf: Path | None = None) -> tuple[Path, Path | None]:
    facts = _load_facts()
    prs = _blank_prs()
    total = 14

    # Slide 1: Cover
    s1 = _new_slide(prs)
    _add_rect(s1, 0, 0, 13.333, 7.5, NAVY)
    _add_rect(s1, 0, 0, 0.28, 7.5, ORANGE)
    _add_text(
        s1,
        0.75,
        0.55,
        11.8,
        0.40,
        "UNIVERSITY OF INFORMATION TECHNOLOGY – VNU-HCM  |  FACULTY OF INFORMATION SYSTEMS",
        font_size=13.0,
        bold=True,
        color=ORANGE,
    )
    _add_text(
        s1,
        0.75,
        1.05,
        11.8,
        0.40,
        "IS355 – BLOCKCHAIN TECHNOLOGY (IS355.R11.CTTT.2) · FINAL DEFENSE PRESENTATION",
        font_size=14.0,
        bold=True,
        color=RGBColor(0xE2, 0xE8, 0xF0),
    )
    _add_text(
        s1,
        0.75,
        1.75,
        11.8,
        1.45,
        "X-SPIDE-G: Graph-Enhanced Explainable Ponzi Detection\nand On-Chain Risk Attestation for Ethereum Smart Contracts",
        font_size=28.0,
        bold=True,
        color=WHITE,
    )
    _add_rect(s1, 0.75, 3.35, 2.8, 0.06, ORANGE)
    _add_text(
        s1,
        0.75,
        3.58,
        11.8,
        0.42,
        "Pre-Registered Empirical Evaluation, Negative Result Transparency & Verified Vyper Quorum Registry",
        font_size=15.0,
        color=RGBColor(0xCB, 0xD5, 0xE1),
    )
    _add_rect(s1, 0.75, 4.35, 11.8, 2.25, DARK_SLATE, line_color=ORANGE, line_pt=1.0, rounded=True)
    _add_text(s1, 0.95, 4.48, 5.5, 0.34, "GROUP 4 – DICTATOR (5 MEMBERS)", font_size=13.5, bold=True, color=ORANGE)
    _add_text(
        s1,
        0.95,
        4.88,
        6.1,
        1.55,
        "1. Phạm Vũ Gia Minh (23520948) – Leader · Audit, Vyper D1/D2/D3, Sepolia E5\n"
        "2. Vũ Thế Vinh (23521801) – Phase 2 X-SPIDE E0–E2 & baseline_v1\n"
        "3. Hoàng Phan Anh Sơn (23521354) – Phase 3 Disassembler & CFG Extraction\n"
        "4. Nguyễn Thiện Nhân (23521084) – Phase 4 25-Fold Stats, S1–S4 & OOF SHAP\n"
        "5. Võ Minh Quân (23521274) – Phase 6 Canonical JSON, IPFS CIDv1 & DApp",
        font_size=11.5,
        color=WHITE,
    )
    _add_text(s1, 7.35, 4.48, 5.0, 0.34, "KEY PROJECT METRICS", font_size=13.5, bold=True, color=ORANGE)
    _add_text(
        s1,
        7.35,
        4.88,
        5.0,
        1.55,
        "▪ Corpus: 7,446 valid contracts (880 Ponzi)\n"
        "▪ Near-clone Ponzi rate: 59.09% (MinHash t=0.90)\n"
        "▪ Best Confirmed ML: E4b PR-AUC 0.8995 (+0.0227)\n"
        "▪ On-Chain Batch D3 (N=100): 3,574.53 gas/case (PASS)\n"
        "▪ Verified Networks: Sepolia & Arbitrum Sepolia (v1.0-final)",
        font_size=11.5,
        color=WHITE,
    )
    _add_text(
        s1,
        0.75,
        6.92,
        11.8,
        0.35,
        "Repository: https://github.com/gminh715/IS355_DICTATOR_X-SPIDE-G   ·   Ho Chi Minh City, November 2026",
        font_size=11.5,
        color=RGBColor(0x94, 0xA3, 0xB8),
    )

    # Slide 2: Motivation, Gaps & RQs
    s2 = _new_slide(prs)
    _header_footer(s2, "1. Motivation, Research Gaps & Research Questions", "Bridging clone-leakage evaluation flaws and single-party ML verdict provenance", 2, total)
    _add_card(
        s2,
        0.45,
        1.15,
        6.05,
        2.75,
        "IDENTIFIED LITERATURE GAPS (G1, G2)",
        [
            ("G1 – Clone Leakage & Uncalibrated Graphs", "X-SPIDE [1] & random-split detectors expose factory clones across folds; static CFG features are rarely tested head-to-head against ordered opcode bigrams."),
            ("G2 – Fragile Off-Chain Verdicts", "Static ML outputs lack immutable hash/XAI commitments, multi-auditor quorum separation, batch scalability, and zero-server-key signing."),
        ],
        accent=NAVY,
        font_size=12.0,
    )
    _add_card(
        s2,
        6.83,
        1.15,
        6.05,
        2.75,
        "CORE CONTRIBUTIONS (I1, I2)",
        [
            ("I1 – Leak-Free Empirical Framework", "CBOR trailer stripping [13] + MinHash near-clone StratifiedGroupKFold (5x5), nested Optuna/vectorizer, Nadeau-Bengio & 8-test Holm stats."),
            ("I2 – Verified Vyper k-of-n Attestation", "Three verified Vyper 0.4.3 contracts (D1/D2/D3), deterministic canonical JSON + IPFS CIDv1, 4-page DApp & client-side ethers.js v6 MetaMask signer."),
        ],
        accent=ORANGE,
        font_size=12.0,
    )
    _add_table(
        s2,
        0.45,
        4.15,
        12.43,
        2.78,
        ["RQ", "Research Question", "Pre-Registered Protocol & Target Criteria"],
        [
            ["RQ1", "How much optimism does bytecode clone leakage introduce in Ethereum Ponzi detection?", "Compare E0 random splits vs leak-free 5x5 StratifiedGroupKFold (E1, E2) after CBOR removal + MinHash group_near."],
            ["RQ2", "Do static CFG semantics (F-GSEM) or stats (F-GSTAT) outperform X-SPIDE unigrams & bigrams (F-BIGRAM)?", "25 nested folds; MDE Delta PR-AUC >= +0.02, 95% NB CI > 0, Holm p < 0.05; S1-S4 sensitivity, E6, OOF SHAP."],
            ["RQ3", "Can a k-of-n Vyper registry anchor ML/XAI evidence under bounded gas and L1/L2 latency?", "E5 benchmark: <= 250k single case, <= 10k/case Merkle batch, <= 2 blocks Sepolia confirmation, T1-T12 reverts."],
        ],
        col_widths=[0.85, 5.45, 6.13],
        font_size=11.0,
    )

    # Slide 3: Architecture & Threat Model
    s3 = _new_slide(prs)
    _header_footer(s3, "2. End-to-End Architecture & Threat Model", "Explicit role isolation: off-chain inference holds zero keys; on-chain contracts isolate owner from auditors", 3, total)
    boxes = [
        (0.45, "LAYER 1: OFFLINE & ML/XAI", NAVY, [
            "Bytecode Disassembly + CBOR Strip",
            "X-SPIDE 99 + F-BIGRAM / F-GSEM",
            "LightGBM Inference (tau*=0.256746)",
            "TreeExplainer SHAP + Basic-Block CFG",
        ]),
        (3.62, "LAYER 2: CANONICAL EVIDENCE", BLUE_ACCENT, [
            "Deterministic UTF-8 Sorted JSON",
            "6-Decimal Fixed Float Serialization",
            "ABI case_id + keccak256 evidence_hash",
            "IPFS CIDv1 + evidence/<id>.json Mirror",
        ]),
        (6.79, "LAYER 3: VYPER k-of-n REGISTRY", ORANGE, [
            "D1 Full Case + Attestation Storage",
            "D2 Compact Event-Only (-31.06% gas)",
            "D3 MerkleBatch O(1) Root Anchoring",
            "Owner != Auditor (Reverts on EOA Bypass)",
        ]),
        (9.96, "LAYER 4: DAPP & PUBLIC AUDIT", GREEN, [
            "4-Page Streamlit Analysis UI",
            "Client ethers.js v6 MetaMask Signer",
            "Anvil (31337) Dev Keys Gated Strictly",
            "Public view verify_evidence(case, hash)",
        ]),
    ]
    for bx, btitle, col, lines in boxes:
        _add_rect(s3, bx, 1.18, 2.92, 2.65, WHITE, line_color=col, line_pt=1.5, rounded=True)
        _add_rect(s3, bx, 1.18, 2.92, 0.42, col)
        _add_text(s3, bx + 0.08, 1.24, 2.76, 0.30, btitle, font_size=11.0, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        _add_bullets(s3, bx + 0.08, 1.70, 2.76, 2.05, [("", ln) for ln in lines], font_size=10.5, space_after=6.0)

    _add_table(
        s3,
        0.45,
        4.05,
        8.25,
        2.85,
        ["Adversarial Attack", "Off-Chain DB Only", "X-SPIDE-G Guarantee & Verified Proof"],
        [
            ["Post-hoc score/SHAP tampering", "Silent rewrite possible", "keccak256 recompute returns verify_evidence == False (T8 live & DApp)."],
            ["Single rogue auditor approval", "Trusted unilaterally", "Stays Pending until k=2 of 3 independent auditors call attest (T3/T5)."],
            ["Compromised Owner self-attest", "Overrides database state", "Contract enforces owner != auditor; tx reverts status=0 (T6 Sepolia)."],
            ["Overwrite / delete case history", "Arbitrary SQL update", "Duplicate case_id reverts (T1); no delete/edit functions; Merkle append-only."],
        ],
        col_widths=[2.35, 1.95, 3.95],
        font_size=10.5,
    )
    _add_card(
        s3,
        8.90,
        4.05,
        3.98,
        2.85,
        "EXPLICIT NON-GOALS & LIMITS",
        [
            ("No On-Chain ML", "LightGBM runs off-chain; EVM checks hashes & quorum votes."),
            ("No Unbounded On-Chain JSON", "Only 32-byte keccak256 hashes + URI strings stored on-chain."),
            ("Owner Testnet Limit", "Deployments use EOA (owner_type='eoa_demo_limit'); production requires Gnosis Safe."),
        ],
        fill=SOFT_ORANGE,
        border=ORANGE,
        accent=ORANGE,
        font_size=10.8,
    )

    # Slide 4: Phase 1 Data Audit
    s4 = _new_slide(prs)
    _header_footer(s4, "3. Data Audit, Clone Clustering & Anti-Leakage Splits", "Quantifying massive bytecode duplication (59.09% Ponzi clones) and selection bias before modeling", 4, total)
    stat_cards = [
        ("7,446", "Valid Contracts (100% Bytecode)", "880 Ponzi · 6,566 Non-Ponzi · 0 conflicts", NAVY),
        ("6,417", "CBOR Trailers Stripped [13]", "1,029 pre-Solidity 0.4.7 unaffected", BLUE_ACCENT),
        ("59.09%", "Ponzi Near-Clone Rate", "520/880 in MinHash LSH multi-groups (t=0.90)", ORANGE),
        ("10", "Unique PG Ponzis Left", "78/89 overlapped X-SPIDE -> Risk R6 E6 check", RED),
    ]
    for idx, (num, title, sub, col) in enumerate(stat_cards):
        cx = 0.45 + idx * 3.15
        _add_rect(s4, cx, 1.18, 2.98, 1.55, WHITE, line_color=col, line_pt=1.5, rounded=True)
        _add_text(s4, cx + 0.12, 1.25, 2.74, 0.55, num, font_size=28.0, bold=True, color=col)
        _add_text(s4, cx + 0.12, 1.84, 2.74, 0.30, title, font_size=12.0, bold=True, color=NAVY)
        _add_text(s4, cx + 0.12, 2.16, 2.74, 0.48, sub, font_size=10.0, color=MUTED)

    _add_card(
        s4,
        0.45,
        2.95,
        6.10,
        3.95,
        "CLONE CLUSTERING & LABEL CONFLICTS",
        [
            ("Exact keccak256 (CBOR-stripped)", "6,145 groups (max size 91); 225/880 (25.57%) Ponzi in multi-groups; 10 mixed-label groups."),
            ("MinHash LSH (5-gram, t=0.90, 128 perms)", "4,711 near-clone groups (max size 99); 520/880 (59.09%) Ponzi + 47.23% non-Ponzi share near-duplicate code; 24 mixed-label clusters."),
            ("Cross-Dataset Overlap", "Blockchain@Unica overlaps 161/182 addresses; PonziGuard .bin leaves 107 non-overlapping (10 Ponzi / 97 non-Ponzi), forcing Risk R6 downgrade."),
            ("55 Frozen Split Artifacts", "25 S_code_group_near + 25 S_code_group_exact + 5 S_full_E0_random saved in Phase 1."),
        ],
        font_size=11.2,
    )
    _add_card(
        s4,
        6.78,
        2.95,
        6.10,
        3.95,
        "RISK R2: 8k EXCLUSION BIAS & MISSING TEMPORAL FIELD",
        [
            ("Selection Shift (Kept n=7,446 vs Dropped n=516)", "Contracts dropped from bytecode_opcode_8k.csv differ sharply on transaction behavior (KS-test):"),
            ("tx_out Median", "0.0 (kept) vs 1.0 (excluded) — KS = 0.2467, p = 2.50e-26."),
            ("lifetime Median", "15.0 days (kept) vs 2.0 days (excluded) — KS = 0.1384, p = 1.58e-08."),
            ("total_tx Median", "5.0 vs 3.0 — KS = 0.2072, p = 1.71e-18; tx_in KS = 0.1656, p = 2.41e-12."),
            ("Missing block_number (S3 Infeasible)", "100% <NA> across X-SPIDE without BigQuery access -> S3 temporal holdout formally reported unfeasible."),
        ],
        fill=SOFT_RED,
        border=RED,
        accent=RED,
        font_size=11.2,
    )

    # Slide 5: RQ1 Baseline Reproduction & Clone Leakage
    s5 = _new_slide(prs)
    _header_footer(s5, "4. RQ1: Baseline Reproduction & Clone-Leakage Impact (E0–E2)", "Quarantining near-clones drops PR-AUC by -0.0382 and F1 by -0.0471; RFE gives zero gain", 5, total)
    _add_table(
        s5,
        0.45,
        1.20,
        12.43,
        3.35,
        ["Configuration", "Split Scheme", "Feats", "PR-AUC", "ROC-AUC", "F1", "P", "R", "Accuracy"],
        [
            ["Published X-SPIDE [1]", "Paper 85/15 random", "47", "—", "0.9770", "0.8670", "0.8700", "0.8640", "0.9690"],
            ["E0 (47-feat notebook)", "Random 85/15 (seed 42)", "47", "0.9173", "0.9772", "0.8340", "0.8504", "0.8182", "0.9615"],
            ["E0 Random 5-fold (GridBest)", "S_full random 5-fold", "99", "0.9149", "0.9768", "0.8589", "0.9158", "0.8091", "0.9686"],
            ["E1 Main Grouped Baseline", "S_code 5x5 group_near", "99", "0.8767 ± 0.0254", "0.9631", "0.8118 ± 0.0275", "0.8374", "0.7909", "0.9568"],
            ["E2 In-Fold RFECV", "S_code 5x5 group_near", "71.4 avg", "0.8768 ± 0.0237", "0.9638", "0.8095 ± 0.0264", "0.8392", "0.7848", "0.9564"],
            ["models/baseline_v1 (Frozen)", "Seed 42 Fold 0 (tau*=0.2567)", "99", "0.8956", "0.9679", "0.8222", "—", "—", "—"],
        ],
        col_widths=[2.50, 2.25, 0.90, 1.50, 1.00, 1.48, 0.90, 0.90, 1.00],
        font_size=10.5,
    )
    _add_card(
        s5,
        0.45,
        4.75,
        6.05,
        2.18,
        "KEY RQ1 FINDING: RANDOM SPLITS OVERSTATE GENERALIZATION",
        [
            ("E0 -> E1 Drop", "-0.0382 PR-AUC (0.9149 -> 0.8767) and -0.0471 F1 (0.8589 -> 0.8118)."),
            ("Clean-Clone Parity Check", "Refitting baseline_v1 in-fold reproduces 0.895561 PR-AUC with max_abs_proba_diff = 0.0."),
        ],
        fill=SOFT_BLUE,
        border=BLUE_ACCENT,
        accent=BLUE_ACCENT,
        font_size=11.5,
    )
    _add_card(
        s5,
        6.83,
        4.75,
        6.05,
        2.18,
        "E2 NESTED RFECV RESULT",
        [
            ("No Meaningful Improvement", "Pruning to 71.4 [39-99] features yields Delta PR-AUC = +0.00003 (p_Holm = 1.00)."),
            ("Conclusion", "Retain full 99 baseline features and strictly enforce S_code group_near for RQ2."),
        ],
        accent=NAVY,
        font_size=11.5,
    )

    # Slide 6: Bytecode Feature Families & Cost
    s6 = _new_slide(prs)
    _header_footer(s6, "5. Phase 3: Bytecode Disassembly, CFG & Extraction Benchmark", "Linear-sweep normalization across 7,446 contracts with zero crashes (16.584 ms median)", 6, total)
    _add_card(
        s6,
        0.45,
        1.20,
        4.0,
        3.40,
        "F-BIGRAM (IN-FOLD TOP-200)",
        [
            ("Opcode Family Grouping", "PUSH1..32 -> PUSH, DUP1..16 -> DUP, SWAP1..16 -> SWAP, LOG0..4 -> LOG."),
            ("Leak-Free Vectorizer", "BigramTopKVectorizer(top_k=200) fitted strictly inside each training fold."),
            ("Intuition", "Captures dispatcher and guard idioms (e.g., CALLVALUE -> ISZERO -> JUMPI, SLOAD -> CALL)."),
        ],
        accent=GREEN,
        font_size=11.0,
    )
    _add_card(
        s6,
        4.67,
        1.20,
        4.0,
        3.40,
        "F-GSTAT (16 GRAPH STATS)",
        [
            ("Opcode Multigraph", "Nodes = normalized opcodes; directed edges = consecutive transitions."),
            ("Features (16)", "Nodes, edges, density, reciprocity, mean out/in degree & weighted strength, entropy, top-1 out/in ratio, self-loop & /L ratios."),
            ("Role", "Global graph summary baseline without sequential local patterns."),
        ],
        accent=NAVY,
        font_size=11.0,
    )
    _add_card(
        s6,
        8.88,
        1.20,
        4.0,
        3.40,
        "F-GSEM (15 STATIC CFG FEATS)",
        [
            ("Stack-Local CFG", "Basic blocks + JUMP/JUMPI targets via local PUSH stack propagation."),
            ("Semantic Signals", "n_blocks, n_cfg_edges, cyclomatic, n_scc_cycles, has_loop_with_call, n_loops_with_call, sstore loops, callvalue->call, call_block_ratio."),
            ("Audit Signals", "unresolved_jump_ratio, selfdestruct reachability, opcode PageRank (CALL, SSTORE)."),
        ],
        accent=ORANGE,
        font_size=11.0,
    )
    _add_table(
        s6,
        0.45,
        4.82,
        12.43,
        2.12,
        ["Extraction Stage (Intel i5-12450H, 15.63 GB RAM, Py3.12)", "Contracts", "Errors", "Median / Contract", "p95 / Contract", "Total Corpus Time"],
        [
            ["Linear-sweep disassembly + normalization", "7,446", "0", "4.041 ms", "13.389 ms", "41.80 s"],
            ["Basic-block CFG + Tarjan SCC + PageRank (F-GSEM)", "7,446", "0", "9.644 ms", "38.288 ms", "95.55 s"],
            ["End-to-end F-BIGRAM + F-GSTAT + F-GSEM pipeline", "7,446", "0 (554 trunc PUSH)", "16.584 ms", "60.213 ms", "165.43 s"],
        ],
        col_widths=[4.48, 1.15, 1.65, 1.75, 1.65, 1.75],
        font_size=10.5,
    )

    # Slide 7: RQ2 Main Ablations & Pre-Registered Stats
    s7 = _new_slide(prs)
    _header_footer(s7, "6. RQ2: Ablation Results & Pre-Registered Holm–Bonferroni Inference", "F-BIGRAM achieves Confirmed Improvement (+0.0227 PR-AUC); F-GSEM yields No Significant Difference (+0.0058)", 7, total)
    _add_table(
        s7,
        0.45,
        1.18,
        6.55,
        3.40,
        ["Exp", "Features", "PR-AUC (mean ± std)", "Delta", "F1", "Verdict vs E1"],
        [
            ["E1", "99 baseline", "0.8767 ± 0.0254", "+0.0000", "0.8118", "Baseline"],
            ["E3", "F-GSTAT (16)", "0.6000 ± 0.0629", "-0.2767", "0.5364", "Weak alone"],
            ["E3b", "F-BIGRAM (200)", "0.9013 ± 0.0191", "+0.0246", "0.8247", "Strong code-only"],
            ["E3c", "F-GSEM (15)", "0.7787 ± 0.0418", "-0.0980", "0.6972", "Confirmed > E3"],
            ["E4", "99 + F-GSTAT", "0.8805 ± 0.0242", "+0.0037", "0.8140", "n.s. (NB p=0.246)"],
            ["E4b", "99 + F-BIGRAM", "0.8995 ± 0.0212", "+0.0227", "0.8263", "Confirmed Improvement"],
            ["E4c", "99 + F-GSEM", "0.8825 ± 0.0233", "+0.0058", "0.8125", "n.s. (NB p=0.220)"],
            ["E4d", "99 + BIGRAM + GSEM", "0.9010 ± 0.0216", "+0.0243", "0.8259", "n.s. vs E4b (+0.0016)"],
        ],
        col_widths=[0.62, 1.55, 1.48, 0.72, 0.70, 1.48],
        font_size=9.5,
    )
    _add_picture_fit(s7, REPO_ROOT / "figures" / "delta_pr_auc_ci.png", 7.15, 1.18, 5.73, 4.05)
    _add_card(
        s7,
        0.45,
        4.72,
        6.55,
        2.22,
        "PRE-REGISTERED STATISTICAL PROTOCOL (m=8 HOLM FAMILY, df=24)",
        [
            ("E4b vs E1 (Confirmed)", "Delta = +0.0227, 95% NB CI [+0.0096, +0.0358], NB t = +3.57, p_Holm = 4.77e-07 (clears MDE >= 0.02)."),
            ("E4c vs E1 (Null)", "Delta = +0.0058, 95% NB CI [-0.0037, +0.0152] crosses 0 -> Negative structural result for scalar F-GSEM."),
            ("E4d vs E4b (Null)", "Adding F-GSEM onto F-BIGRAM adds +0.0016 [-0.0075, +0.0107], p_Holm = 1.00 -> No marginal utility."),
        ],
        fill=SOFT_BLUE,
        border=BLUE_ACCENT,
        accent=BLUE_ACCENT,
        font_size=10.2,
    )
    _add_text(
        s7,
        7.15,
        5.35,
        5.73,
        1.50,
        "Figure: Nadeau-Bengio corrected 95% confidence intervals (df=24) against the pre-registered MDE threshold (+0.02 PR-AUC). Only explicit in-fold opcode bigrams (E4b vs E1) and E3c vs E3 pass all pre-registered confirmation gates.",
        font_size=10.5,
        color=MUTED,
    )

    # Slide 8: Sensitivity & External E6
    s8 = _new_slide(prs)
    _header_footer(s8, "7. Sensitivity Analyses (S1–S4) & External PonziGuard Check (E6)", "Validating robustness against CBOR/opcode choices while demonstrating residual exact-split leakage", 8, total)
    _add_table(
        s8,
        0.45,
        1.20,
        12.43,
        3.25,
        ["Study", "Variant", "Paired", "PR-AUC", "Delta PR-AUC", "Delta F1", "Finding"],
        [
            ["S1 Split Granularity", "E1_S1_group_exact", "No", "0.9051", "+0.0283", "+0.0261", "Exact grouping still leaks near-clones vs MinHash group_near!"],
            ["S1 Split Granularity", "E4c_S1_group_exact", "No", "0.9097", "+0.0272", "+0.0325", "Confirms MinHash grouping is essential for unbiased eval."],
            ["S2 CBOR Metadata", "E1_S2_cbor_stripped", "Yes", "0.8792", "+0.0024", "-0.0022", "Recomputing 76 opcodes from stripped hex leaves baseline stable."],
            ["S2 CBOR Metadata", "E4c_S2_raw_cbor", "Yes", "0.8853", "+0.0028", "+0.0016", "CBOR bytes barely shift F-GSEM (<= 0.0028 PR-AUC)."],
            ["S4 Mnemonic Norm", "E4b_S4_raw_opcodes", "Yes", "0.8969", "-0.0025", "-0.0037", "PUSH1..32 normalization beats/matches raw mnemonics."],
            ["S3 Temporal Holdout", "N/A", "No", "N/A", "N/A", "N/A", "Unfeasible: block_number is 100% <NA> without BigQuery."],
        ],
        col_widths=[1.85, 1.85, 0.72, 0.85, 1.05, 0.90, 5.21],
        font_size=10.0,
    )
    _add_picture_fit(s8, REPO_ROOT / "figures" / "pr_curves.png", 0.45, 4.65, 5.30, 2.35)
    _add_card(
        s8,
        5.98,
        4.65,
        6.90,
        2.35,
        "E6 EXTERNAL PONGIGUARD SANITY CHECK (RISK R6 DOWNGRADE)",
        [
            ("Independent Subset", "78/89 extracted PonziGuard Ponzi runtimes overlap X-SPIDE -> remaining n = 107 (10 Ponzi / 97 non-Ponzi) evaluated code-only (E3b style)."),
            ("Score & Bootstrap CI", "PR-AUC = 0.6535 (95% stratified bootstrap CI [0.3965, 0.9141]); F1 = 0.6667 (TP=6, FP=2, TN=95, FN=4)."),
            ("Why Lower Than In-Domain 0.9013?", "Strict cross-dataset novelty + 0 account transaction features + n=10 positive sample variance."),
        ],
        fill=SOFT_ORANGE,
        border=ORANGE,
        accent=ORANGE,
        font_size=10.8,
    )

    # Slide 9: XAI & Error Modes
    s9 = _new_slide(prs)
    _header_footer(s9, "8. Explainability (OOF SHAP) & Structural Error Audit", "Domain-faithful F-GSEM attributions clarify why benign payout loops cause False Positives", 9, total)
    _add_picture_fit(s9, REPO_ROOT / "figures" / "shap_beeswarm_E4c.png", 0.45, 1.18, 4.25, 3.60)
    _add_picture_fit(s9, REPO_ROOT / "figures" / "cfg_tp.png", 4.88, 1.18, 3.90, 3.60)
    _add_card(
        s9,
        8.96,
        1.18,
        3.92,
        3.60,
        "OOF TREEEXPLAINER METRICS (SEED 42)",
        [
            ("call_block_ratio", "mean |SHAP| = 0.2833, Spearman r = +0.874."),
            ("n_loops_with_call", "mean |SHAP| = 0.2061 (SHAP +1.052 when >0 vs -0.114)."),
            ("n_blocks_with_call", "mean |SHAP| = 0.1707; has_loop_with_call (+0.3191 vs -0.0305)."),
            ("unresolved_jump_ratio", "mean |SHAP| = 0.1520, Spearman r = -0.897; 526/7,446 (7.06%) > 0.50 (clears Risk R4 <50%)."),
        ],
        accent=NAVY,
        font_size=10.5,
    )
    _add_card(
        s9,
        0.45,
        4.95,
        12.43,
        1.98,
        "ERROR ANALYSIS ON SEED-42 OOF E4c (TP=685, FP=125, TN=6,441, FN=195; TOP-24 AUDIT SAMPLE)",
        [
            ("False Positives (FP=125)", "Legitimate reward/airdrop payout distributors containing CALL-inside-loop SCCs (e.g., xspide_06872, xspide_02699) + 14 FPs inside mixed-label clone clusters."),
            ("False Negatives (FN=195)", "Minimal/acyclic dispatcher Ponzi wrappers lacking static loop+CALL motifs (e.g., xspide_04097) + 38 FNs inside mixed-label clone clusters."),
        ],
        fill=SOFT_BLUE,
        border=BLUE_ACCENT,
        accent=BLUE_ACCENT,
        font_size=11.0,
    )

    # Slide 10: Smart Contracts & Canonical Evidence
    s10 = _new_slide(prs)
    _header_footer(s10, "9. Verified Vyper Contracts (D1/D2/D3) & Canonical Evidence", "34 unit/fuzz contract tests + 100% Vyper revert branch coverage; zero server-side live private keys", 10, total)
    _add_table(
        s10,
        0.45,
        1.18,
        12.43,
        2.55,
        ["Network (chainId)", "Variant", "Deployed & Verified Address (Vyper 0.4.3)", "State Design", "Governance / Coverage"],
        [
            ["Ethereum Sepolia (11155111)", "D1", "0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77", "Full Case + Attestation", "k=2 of 3; 16/16 revert branches"],
            ["Ethereum Sepolia (11155111)", "D2", "0x693632c45108A9ca25a7F9d693c00554EeDD1EB1", "Compact + Event payload", "k=2 of 3; 16/16 revert branches"],
            ["Ethereum Sepolia (11155111)", "D3", "0xf04fd7BD0Ee4DBf28d19D7D02988ac01fD989eF2", "Merkle root O(1) batch", "k=2 of 3; 14/14 revert branches"],
            ["Arbitrum Sepolia (421614)", "D1", "0x14895F5e1f7F1aC5C58b35dA6d57674Aa5951b77", "Full Case + Attestation", "Etherscan v2 Pass - Verified"],
            ["Arbitrum Sepolia (421614)", "D3", "0x693632c45108A9ca25a7F9d693c00554EeDD1EB1", "Merkle root O(1) batch", "Etherscan v2 Pass - Verified"],
        ],
        col_widths=[2.45, 0.75, 4.35, 2.28, 2.60],
        font_size=10.2,
    )
    _add_card(
        s10,
        0.45,
        3.92,
        6.05,
        3.02,
        "CANONICAL EVIDENCE PIPELINE (PHASE 6)",
        [
            ("Canonical JSON (schema 1.0.0)", "Sorted UTF-8 keys, compact separators, fixed 6-decimal numeric formatting, embedded model_hash & shap_digest."),
            ("Cryptographic Identifiers", "evidence_hash = keccak256(canonical_bytes); case_id = keccak256(abi.encode(address, contract_id, model_version))."),
            ("Dual Availability", "IPFS CIDv1 raw-block (bafk...) + persistent local Git mirror evidence/<case_id>.json."),
        ],
        accent=NAVY,
        font_size=11.0,
    )
    _add_card(
        s10,
        6.83,
        3.92,
        6.05,
        3.02,
        "SECURITY-FIRST CLIENT SIGNING",
        [
            ("Standalone ethers.js v6 Signer", "signer/index.html receives pre-filled case_id, evidence_hash, and ipfs://... via URL params and signs strictly inside MetaMask."),
            ("Zero Live Keys on Server", "Streamlit server only executes read-only eth_call/event filters on public networks."),
            ("Anvil Key Gate (chainId == 31337)", "Pre-funded dev test keys rejected on any non-Anvil RPC."),
        ],
        fill=SOFT_GREEN,
        border=GREEN,
        accent=GREEN,
        font_size=11.0,
    )

    # Slide 11: Live Browser DApp Screenshots
    s11 = _new_slide(prs)
    _header_footer(s11, "10. Live E2E DApp Walkthrough (Case xspide_00439)", "Real browser verification: SHAP+CFG prediction -> 2-of-3 quorum -> Verified event log -> 1-byte tamper rejection", 11, total)
    shots = [
        ("1) Page 1: SHAP & CFG (score=0.998390)", "02_page1_shap_cfg.png", 0.45, 1.18),
        ("2) Page 3: 2-of-3 Quorum Approved", "06_page3_quorum_approved.png", 4.65, 1.18),
        ("3) Client Signer: ethers.js v6 MetaMask", "10_signer_metamask.png", 8.85, 1.18),
        ("4) Page 4: ✅ VERIFIED + Event Audit", "08_page4_verified_events.png", 0.45, 4.18),
        ("5) Page 4: ❌ 1-Byte Tamper Reject", "09_page4_tampered_reject.png", 6.78, 4.18),
    ]
    widths = [3.95, 3.95, 4.03, 6.10, 6.10]
    heights = [2.42, 2.42, 2.42, 2.42, 2.42]
    for idx, (cap, fname, lx, ty) in enumerate(shots):
        w = widths[idx]
        h = heights[idx]
        _add_picture_fit(s11, REPO_ROOT / "demo" / "screenshots" / fname, lx, ty, w, h)
        col = GREEN if "VERIFIED" in cap else (RED if "Tamper" in cap else NAVY)
        _add_text(s11, lx, ty + h + 0.04, w, 0.28, cap, font_size=10.5, bold=True, color=col, align=PP_ALIGN.CENTER)

    # Slide 12: RQ3 E5 Gas, Cost, Latency & Sepolia Proofs
    s12 = _new_slide(prs)
    _header_footer(s12, "11. RQ3: On-Chain Gas, Cost, Latency & Live Sepolia Proofs (E5)", "D1 fails 250k ceiling (427,461 gas), D3 amortizes to 3,574.53 gas/case (PASS), Sepolia settles in 1.00 block", 12, total)
    _add_picture_fit(s12, REPO_ROOT / "figures" / "gas_vs_batch.png", 0.45, 1.18, 6.25, 3.85)
    _add_table(
        s12,
        6.90,
        1.18,
        5.98,
        3.50,
        ["Variant / Metric", "Cancun PyEVM", "Sepolia Live", "Target"],
        [
            ["D1 deploy", "1,068,183", "7,365,849*", "One-time"],
            ["D1 case + 2x attest", "427,461", "1,648,029*", "FAIL (>250k)"],
            ["D2 EventOnly (k=2)", "294,706 (-31%)", "987,566*", "FAIL (>250k)"],
            ["D3 Merkle N=100 (/case)", "3,574.53", "13,142.73*", "PASS (<=10k)"],
            ["D3 Merkle N=1,000 (/case)", "357.46", "—", "PASS (<=10k)"],
            ["D1 USD @ 0.0844 gwei", "$0.068594", "Arb: $0.0163*", "Mainnet ref"],
            ["D3 N=100 USD @ 0.0844", "$0.000574", "Arb: $0.00014*", "L2 < $0.01"],
        ],
        col_widths=[1.95, 1.35, 1.38, 1.30],
        font_size=9.5,
    )
    _add_card(
        s12,
        0.45,
        5.15,
        12.43,
        1.80,
        "LIVE TESTNET LATENCY (n=30 EACH) & SEPOLIA SECURITY REVERT PROOFS",
        [
            ("Confirmation Latency (RQ3-04)", "Sepolia: median 10.357 s / 1.00 block, p95 = 11.217 s (PASS <= 2 blocks). Arbitrum Sepolia: median 1.226 s / 4.0 L2 blocks, p95 = 1.675 s."),
            ("Live Sepolia Proofs (RQ3-05)", "5/5 T1/T6 revert checks verified status=0 (e.g., owner attest tx 0x56764e897eec...); T8 verify_evidence exact=True & 1-byte tampered=False."),
            ("Accounting Note (*)", "Sepolia Glamsterdam/EIP-8037 reprices state creation (~693k register_case); Arbitrum Sepolia gasUsedForL1=0x0 (reference only)."),
        ],
        fill=SOFT_BLUE,
        border=BLUE_ACCENT,
        accent=BLUE_ACCENT,
        font_size=10.3,
    )

    # Slide 13: Negative Results & Threats to Validity
    s13 = _new_slide(prs)
    _header_footer(s13, "12. Negative Results, Threats to Validity & Limitations", "Rigorous scientific reporting without post-hoc hypothesis or threshold manipulation", 13, total)
    _add_card(
        s13,
        0.45,
        1.18,
        6.05,
        2.75,
        "NEGATIVE RESULT 1: WHY F-GSEM LOST TO F-BIGRAM",
        [
            ("Root Cause", "Solidity 0.4-0.5 dynamic dispatch & loop exits route JUMP/JUMPI via stack/memory pointers: median 19.18% (and 526/7,446 > 50%) jumps remain unresolved statically, fragmenting SCC loop back-edges."),
            ("Why Bigrams Won", "F-BIGRAM preserves micro-idioms (CALLVALUE->ISZERO->JUMPI) losslessly, achieving +0.0227 PR-AUC (and 0.9013 code-only)."),
        ],
        fill=SOFT_RED,
        border=RED,
        accent=RED,
        font_size=11.0,
    )
    _add_card(
        s13,
        6.83,
        1.18,
        6.05,
        2.75,
        "NEGATIVE RESULT 2: WHY D1 EXCEEDED 250k GAS",
        [
            ("Storage Allocation Cost", "Storing 10-field Case struct + two cold per-auditor mappings incurs three cold SSTORE trees -> 427,461 Cancun gas (+70.98% over 250k ceiling)."),
            ("Architectural Resolution", "Kept FAIL verdict verbatim; validated D3_MerkleBatch (3,574.53 gas/case at N=100; 357.46 at N=1,000) for scalable registry anchoring."),
        ],
        fill=SOFT_ORANGE,
        border=ORANGE,
        accent=ORANGE,
        font_size=11.0,
    )
    _add_card(
        s13,
        0.45,
        4.12,
        12.43,
        2.80,
        "THREATS TO VALIDITY & FUTURE WORK",
        [
            ("Internal Label Noise", "10 exact-clone and 24 near-clone groups carry mixed Ponzi/non-Ponzi labels (causing 14 FPs + 38 FNs in E4c)."),
            ("Construct & Testnet Limits", "Static disassembly skips symbolic execution; live deployments currently use EOA owners (eoa_demo_limit), Arb-Sepolia L1 gas=0x0, Sepolia EIP-8037."),
            ("Temporal & External Limits", "Missing block_number prevents S3 temporal holdout on modern proxy/diamond contracts; 8k subset bias (Risk R2); PG only 10 independent Ponzis (Risk R6)."),
            ("Roadmap", "Migrate owners to 2-of-3 Gnosis Safe, use symbolic IR decompilation (Gigahorse/Vandal), pin IPFS via Pinata/Web3.Storage, and test EIP-712 vote aggregation."),
        ],
        accent=NAVY,
        font_size=11.0,
    )

    # Slide 14: Summary & Reproducibility Package
    s14 = _new_slide(prs)
    _header_footer(s14, "13. Summary of Deliverables & Reproducibility (v1.0-final)", "Every claim links deterministically via results/traceability_matrix.csv and clean-clone scripts", 14, total)
    _add_table(
        s14,
        0.45,
        1.18,
        7.55,
        3.55,
        ["Deliverable", "Artifact Location", "Verification Status"],
        [
            ["Final Report (18p)", "4_DICTATOR_IS355_Final_Report.{docx,pdf} + reports/final_report.md", "Compiled & verified"],
            ["Presentation (14s)", "4_DICTATOR_IS355_Final_Presentation.{pptx,pdf}", "14 widescreen slides"],
            ["Demo Video & Script", "demo/X-SPIDE-G_demo.mp4 + reports/demo_script.md", "1080p MP4 (3–5 min)"],
            ["Traceability Matrix", "results/traceability_matrix.csv + reports/traceability_matrix.md", "39 mapped IDs"],
            ["Defense Q&A Bank", "reports/defense_qa.md (8 Appendix D Qs + extended audit)", "Metric-ID cited"],
            ["Reproducibility Suite", "requirements.txt, pyproject.toml, Makefile, scripts/run_all.py", "E1 & clean-clone tested"],
        ],
        col_widths=[1.95, 3.90, 1.70],
        font_size=10.0,
    )
    _add_card(
        s14,
        8.25,
        1.18,
        4.63,
        3.55,
        "ONE-COMMAND REPRODUCIBILITY",
        [
            ("Unified Runner", "python -m scripts.run_all --mode verify"),
            ("Clean-Clone E1 + Contracts", "python -m scripts.run_all --mode clean-clone"),
            ("Full Test Suite", "pytest -v (data, features, evidence, 34 contracts, Phase 8 checks)"),
            ("Interactive DApp", "python -m scripts.run_dapp --with-anvil-rpc"),
        ],
        fill=SOFT_BLUE,
        border=BLUE_ACCENT,
        accent=BLUE_ACCENT,
        font_size=10.8,
    )
    _add_rect(s14, 0.45, 4.95, 12.43, 1.98, NAVY, line_color=ORANGE, line_pt=1.5, rounded=True)
    _add_text(
        s14,
        0.75,
        5.12,
        11.83,
        0.42,
        "CONCLUSION & DEFENSE TAKEAWAY",
        font_size=14.0,
        bold=True,
        color=ORANGE,
    )
    _add_text(
        s14,
        0.75,
        5.58,
        11.83,
        1.20,
        "X-SPIDE-G demonstrates that clone-aware evaluation cuts illusory Ponzi detection gains (-0.0382 PR-AUC), explicit opcode bigrams significantly outperform baseline features (+0.0227 PR-AUC, p_Holm = 4.77e-07) where scalar static CFG features plateau, and verified Vyper k-of-n Merkle batching anchors explainable audit evidence at 3,574.53 gas/case (< $0.001 at L1 reference gas) with zero server-side key exposure.",
        font_size=12.5,
        color=WHITE,
    )

    prs.save(str(out_pptx))
    print(f"Saved Presentation PPTX: {out_pptx} ({out_pptx.stat().st_size:,} bytes, {len(prs.slides)} slides)")

    if out_pdf is not None:
        import win32com.client  # type: ignore

        ppt = win32com.client.Dispatch("PowerPoint.Application")
        pres = ppt.Presentations.Open(str(out_pptx.resolve()), ReadOnly=True, Untitled=False, WithWindow=False)
        try:
            pres.SaveAs(str(out_pdf.resolve()), 32)  # ppSaveAsPDF
            preview_dir = REPO_ROOT / "demo" / "_slide_previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
            for idx in (1, 7, 11, 12):
                pres.Slides(idx).Export(str((preview_dir / f"slide_{idx:02d}.png").resolve()), "PNG", 1280, 720)
        finally:
            pres.Close()
            ppt.Quit()
        print(f"Exported Presentation PDF: {out_pdf} ({out_pdf.stat().st_size:,} bytes)")

    return out_pptx, out_pdf


def build_demo_video(out_mp4: Path) -> Path:
    """Build a 14-scene 1080p ~214s walkthrough video using PowerPoint COM CreateVideo."""
    prs = _blank_prs()
    total_scenes = 14
    durations = [12, 15, 14, 14, 16, 15, 16, 16, 16, 16, 14, 16, 18, 16]  # sum = 214s (3m34s)

    def _video_frame(
        idx: int,
        step_badge: str,
        title: str,
        narration: str,
        img_path: Path | None = None,
        card_title: str = "",
        card_lines: list[str] | None = None,
        accent: RGBColor = ORANGE,
    ) -> None:
        s = _new_slide(prs)
        _add_rect(s, 0, 0, 13.333, 7.5, NAVY)
        _add_rect(s, 0, 0, 13.333, 0.78, DARK_SLATE)
        _add_rect(s, 0, 0.78, 13.333, 0.04, accent)

        _add_rect(s, 0.35, 0.14, 1.85, 0.48, accent, rounded=True)
        _add_text(s, 0.35, 0.19, 1.85, 0.38, step_badge, font_size=12.5, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        _add_text(s, 2.38, 0.16, 9.40, 0.46, title, font_size=19.0, bold=True, color=WHITE)
        _add_text(s, 11.85, 0.22, 1.15, 0.34, f"{idx}/{total_scenes}", font_size=12.0, bold=True, color=RGBColor(0xCB, 0xD5, 0xE1), align=PP_ALIGN.RIGHT)

        if img_path is not None and card_lines:
            _add_picture_fit(s, img_path, 0.35, 0.96, 8.75, 5.18)
            _add_rect(s, 9.30, 0.96, 3.68, 5.18, DARK_SLATE, line_color=accent, line_pt=1.5, rounded=True)
            _add_rect(s, 9.30, 0.96, 3.68, 0.42, accent)
            _add_text(s, 9.42, 1.02, 3.44, 0.32, card_title, font_size=12.0, bold=True, color=WHITE)
            _add_text(s, 9.44, 1.50, 3.40, 4.45, "\n\n".join(card_lines), font_size=12.0, color=WHITE)
        elif img_path is not None:
            _add_picture_fit(s, img_path, 0.45, 0.96, 12.43, 5.18)
        else:
            _add_rect(s, 0.55, 1.05, 12.23, 5.00, DARK_SLATE, line_color=accent, line_pt=1.5, rounded=True)
            _add_text(s, 0.85, 1.25, 11.63, 0.42, card_title, font_size=16.0, bold=True, color=accent)
            _add_text(s, 0.85, 1.80, 11.63, 4.05, "\n".join(card_lines or []), font_size=13.5, color=WHITE, font_name=FONT_MONO if "TERMINAL" in card_title else FONT_BODY)

        _add_rect(s, 0, 6.28, 13.333, 1.22, RGBColor(0x07, 0x0D, 0x1A))
        _add_rect(s, 0, 6.28, 13.333, 0.03, ORANGE)
        _add_text(s, 0.45, 6.38, 12.43, 1.02, narration, font_size=13.0, color=WHITE)

    shots = REPO_ROOT / "demo" / "screenshots"

    _video_frame(
        1, "INTRO", "X-SPIDE-G Live Demo: Clone-Safe ML + Verified On-Chain Attestation",
        "Welcome to the X-SPIDE-G end-to-end demo (Group 4 - DICTATOR, IS355). We trace contract xspide_00439 from LightGBM+SHAP+CFG risk analysis through IPFS canonical anchoring, 2-of-3 quorum approval, zero-server-key signing, and 1-byte tamper rejection.",
        card_title="DEMO SCENARIO: TARGET CONTRACT xspide_00439",
        card_lines=[
            "1. Off-Chain Analysis: Load unseen test contract xspide_00439 via frozen baseline_v1 (tau* = 0.256746).",
            "2. Evidence Packaging: Canonical UTF-8 JSON + 6-decimal floats -> keccak256 evidence_hash + IPFS CIDv1 + Git mirror.",
            "3. Multi-Auditor Quorum: Deploy & register on EVM, then collect k=2 of 3 independent Approve attestations.",
            "4. Integrity Verification: Verify exact evidence on-chain (True), then mutate 1 byte and prove immediate rejection (False).",
        ],
    )
    _video_frame(
        2, "ARCH", "Four-Layer Trust Architecture & Role Separation",
        "Trusted roles are strictly separated: the off-chain ML and DApp server produces deterministic evidence and read-only queries with zero live private keys, while Vyper 0.4.3 enforces that neither the governance owner nor any single auditor can unilaterally finalize verdicts.",
        card_title="TRUST BOUNDARIES & PRE-REGISTERED INVARIANTS",
        card_lines=[
            "[Off-Chain ML Engine]   LightGBM + SHAP + Stack-Local Basic-Block CFG -> Score + shap_digest (Untrusted / Zero Keys)",
            "[Canonical Evidence]    RFC-style Sorted JSON -> abi.encode case_id -> keccak256 evidence_hash -> IPFS CIDv1 (bafk...)",
            "[Vyper 0.4.3 Registry]  D1 Full Storage | D2 Compact Events | D3 Merkle Batch (100% branch cov; owner != auditor)",
            "[Client Signer & Audit] ethers.js v6 MetaMask Browser Signer | view verify_evidence(case_id, recomputed_hash)",
        ],
        accent=BLUE_ACCENT,
    )
    _video_frame(
        3, "CLI PROOF", "Verified Phase 6.4 CLI E2E + Sepolia Read Check",
        "Executing scripts/run_phase6_e2e_demo confirms live read connectivity to verified D1 on Ethereum Sepolia alongside a deterministic local Anvil E2E run: after Auditor #1 registers Pending(1/2), Auditor #2 completes Approved(2/2), and a 1-byte tamper flips verify_evidence from true to false.",
        card_title="TERMINAL OUTPUT: python -m scripts.run_phase6_e2e_demo",
        card_lines=[
            "$ .\\.venv\\Scripts\\python.exe -m scripts.run_phase6_e2e_demo",
            "\"sepolia_read_check\": {\"network\": \"sepolia\", \"connected\": true, \"quorum_k\": 2}",
            "\"case_id\": \"0x5b7624e00332bf67a30b0f9957113f45481522a21707a396f0d60ace93bb842a\"",
            "\"status_after_register\": \"Pending\", \"approve_count_1\": 1",
            "\"status_after_attest_2\": \"Approved\", \"approve_count_2\": 2",
            "\"verify_exact\": true, \"verify_tampered_1byte\": false",
        ],
        accent=GREEN,
    )
    _video_frame(
        4, "STEP 1", "DApp Page 1: Selecting Contract xspide_00439 for Risk Scoring",
        "Inside the live 4-page Streamlit DApp running on localhost:8501 with Anvil RPC, we select test-fold contract xspide_00439. Frozen LightGBM model baseline_v1 computes risk score 0.998390, far above threshold tau* = 0.256746, raising an immediate PONZI risk flag.",
        img_path=shots / "01_page1_input.png",
        card_title="PAGE 1: MODEL SCORING",
        card_lines=[
            "Contract: xspide_00439 (unseen holdout test vector)",
            "Model: baseline_v1 (hash 0x5d00194582127b30...)",
            "Risk Score: 0.998390 (>= tau* 0.256746 -> PONZI)",
        ],
    )
    _video_frame(
        5, "STEP 2", "DApp Page 1: Local SHAP Drivers & Structural Evidence",
        "TreeExplainer decomposes the 0.998390 probability into auditable feature attributions, pairing top SHAP drivers with extracted structural descriptors so human auditors can inspect why the bytecode triggered a Ponzi alert before signing any on-chain transaction.",
        img_path=shots / "02_page1_shap_cfg.png",
        card_title="LOCAL XAI BREAKDOWN",
        card_lines=[
            "Top Positive Drivers: Account inflow concentration + opcode frequency patterns.",
            "CFG Context: Extracts CALL-in-loop and unresolved jump telemetry at ~16.6 ms.",
            "Audit Readiness: SHAP vector hashed into canonical shap_digest.",
        ],
    )
    _video_frame(
        6, "STEP 3", "DApp Page 1: Disassembled Basic-Block Control-Flow Graph",
        "Inspecting the lower panel shows the interactive basic-block CFG constructed from CBOR-stripped runtime bytecode. Call-containing strongly connected components and control-flow paths are highlighted directly for analyst inspection.",
        img_path=shots / "03_page1_cfg_detail.png",
        card_title="BASIC-BLOCK CFG VIEW",
        card_lines=[
            "CBOR Trailer Stripped cleanly before linear-sweep disassembly.",
            "Normalized opcodes group PUSH/DUP/SWAP/LOG families.",
            "Call blocks and unresolved indirect jump ratios reported transparently.",
        ],
    )
    _video_frame(
        7, "STEP 4", "DApp Page 2: Canonical JSON, keccak256 Hash & IPFS CIDv1",
        "Moving to Page 2, X-SPIDE-G serializes the prediction, SHAP top drivers, and CFG metrics into canonical UTF-8 JSON with fixed 6-decimal floats. Computing keccak256 yields a deterministic evidence_hash and IPFS CIDv1 raw block while saving evidence/<case_id>.json as a local Git-verifiable mirror.",
        img_path=shots / "04_page2_evidence_cid.png",
        card_title="CANONICAL EVIDENCE",
        card_lines=[
            "Schema v1.0.0: Deterministic key ordering & fixed decimal formatting.",
            "case_id: 0x5b7624e00332bf67...",
            "Storage: IPFS CIDv1 URI + evidence/0x5b76...842a.json persisted on disk.",
        ],
        accent=BLUE_ACCENT,
    )
    _video_frame(
        8, "STEP 5", "DApp Page 3: Auditor #1 Registers Case On-Chain (Pending 1/2)",
        "On Page 3, Auditor #1 signs register_case on the local Anvil chain (tx 0xac93319f..., 129,311 gas), committing case_id, evidence_hash, and the IPFS URI into Vyper storage. Because quorum requires k=2 of 3 independent auditors, the verdict remains Pending.",
        img_path=shots / "05_page3_sign_tx.png",
        card_title="ON-CHAIN REGISTRATION",
        card_lines=[
            "Function: register_case(case_id, addr, evidence_hash, ipfs_uri, verdict)",
            "Transaction: 0xac93319f... (gasUsed = 129,311)",
            "Quorum Rule: 1/2 signatures -> Status = Pending (cannot self-approve).",
        ],
    )
    _video_frame(
        9, "STEP 6", "DApp Page 3: Auditor #2 Completes k=2 Quorum -> Approved",
        "Next, independent Auditor #2 submits attest(case_id, verdict=1). The contract increments approve_count to 2 and transitions status cleanly to 1 (Approved). Note that the DApp's built-in test signer keys are strictly gated to Anvil chainId 31337.",
        img_path=shots / "06_page3_quorum_approved.png",
        card_title="QUORUM TRANSITION",
        card_lines=[
            "Auditor #2: Independent wallet signs attest(case_id, Approve).",
            "Result: approve_count = 2 >= quorum_k = 2.",
            "Final State: status = 1 (Approved) emitted permanently in Attested event.",
        ],
        accent=GREEN,
    )
    _video_frame(
        10, "STEP 7", "Zero-Server-Key Client Signer (ethers.js v6 + MetaMask)",
        "For Ethereum Sepolia and Arbitrum Sepolia, clicking 'Open Browser Signer' opens standalone signer/index.html served cleanly over HTTP. All calldata fields are pre-filled via URL parameters and signed exclusively inside the auditor's MetaMask wallet—the server never touches live keys.",
        img_path=shots / "10_signer_metamask.png",
        card_title="CLIENT-SIDE SIGNING",
        card_lines=[
            "URL Pre-fill: case_id, evidence_hash, ipfs://... URI.",
            "Wallet Isolation: ethers.js v6 BrowserProvider connects directly to MetaMask.",
            "Owner Separation: Governance owner calling attest reverts (verified live on Sepolia T6).",
        ],
        accent=ORANGE,
    )
    _video_frame(
        11, "STEP 8", "DApp Page 4: Public Quorum State & Audit Verification",
        "Any ecosystem participant can open Page 4 to verify an attestation independently. Entering case_id queries live RPC view functions, immediately displaying the 2-of-2 Approved status without trusting any off-chain database.",
        img_path=shots / "07_page4_quorum_status.png",
        card_title="PUBLIC AUDIT QUERY",
        card_lines=[
            "Read-Only RPC Check: No wallet or API secret needed to verify.",
            "Quorum Display: Approve 2 / 2 · Reject 0 · NeedsReview 0.",
            "Status Badge: Approved (Finalized on-chain).",
        ],
    )
    _video_frame(
        12, "STEP 9", "DApp Page 4: Hash Integrity Proof -> ✅ VERIFIED & Events",
        "Loading the canonical JSON artifact recomputes its keccak256 digest and queries D1.verify_evidence(case_id, digest). The smart contract returns True (green VERIFIED badge), accompanied by the full chronological CaseRegistered and Attested event trail.",
        img_path=shots / "08_page4_verified_events.png",
        card_title="✅ INTEGRITY VERIFIED",
        card_lines=[
            "On-Chain Hash == Recomputed Canonical keccak256 Digest.",
            "Contract Call: verify_evidence(...) -> True.",
            "Event Log: Immutable CaseRegistered + 2x Attested rows confirmed.",
        ],
        accent=GREEN,
    )
    _video_frame(
        13, "STEP 10", "DApp Page 4: 1-Byte Tamper Simulation -> ❌ TAMPERED",
        "Finally, we simulate an adversary modifying a single byte inside the evidence JSON—changing one numeric digit in the off-chain report. Recomputing keccak256 produces 0x342fecac..., and on-chain verify_evidence immediately returns False (red TAMPERED / MISMATCH alert).",
        img_path=shots / "09_page4_tampered_reject.png",
        card_title="❌ TAMPER DETECTED",
        card_lines=[
            "Simulated Attack: 1-byte mutation inside off-chain JSON payload.",
            "Recomputed Hash: 0x342fecac... != Anchored On-Chain Digest.",
            "Contract Verdict: verify_evidence(...) -> False (Cryptographic Proof of Tampering).",
        ],
        accent=RED,
    )
    _video_frame(
        14, "CLOSING", "Empirical Summary: Batch Scaling (D3) & Final Repository (v1.0-final)",
        "To summarize: while single-case D1 storage costs 427,461 Cancun gas (reported honestly as FAIL against our 250k limit), D3 Merkle batching amortizes on-chain anchoring to 3,574.53 gas per contract at N=100 (PASS), confirming in 1 block on Sepolia and 1.23 seconds on Arbitrum Sepolia. Thank you!",
        img_path=REPO_ROOT / "figures" / "gas_vs_batch.png",
        card_title="X-SPIDE-G KEY OUTCOMES",
        card_lines=[
            "RQ1: Near-clone quarantine removes -0.0382 PR-AUC leakage.",
            "RQ2: F-BIGRAM Confirmed (+0.0227 PR-AUC); F-GSEM Null (+0.0058).",
            "RQ3: D3 N=100 = 3,574.53 gas/case (PASS); Arb-Sepolia 1.226 s finality.",
            "Reproduce: python -m scripts.run_all --mode verify  (Tag: v1.0-final)",
        ],
        accent=ORANGE,
    )

    for idx, dur in enumerate(durations):
        slide = prs.slides[idx]
        # Configure PowerPoint slide show transition timing in XML
        from lxml import etree  # type: ignore

        ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
        trans = slide._element.find(f"{{{ns_p}}}transition")
        if trans is None:
            trans = etree.SubElement(slide._element, f"{{{ns_p}}}transition")
        trans.set("advTm", str(int(dur * 1000)))

    SCRATCH_STORYBOARD.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(SCRATCH_STORYBOARD))
    print(f"Built storyboard PPTX ({len(prs.slides)} scenes, {sum(durations)}s total)")

    import win32com.client  # type: ignore

    ppt = win32com.client.Dispatch("PowerPoint.Application")
    pres = ppt.Presentations.Open(str(SCRATCH_STORYBOARD.resolve()), ReadOnly=False, Untitled=False, WithWindow=False)
    try:
        for idx, dur in enumerate(durations, start=1):
            ss = pres.Slides(idx).SlideShowTransition
            ss.AdvanceOnTime = True
            ss.AdvanceTime = float(dur)
        pres.Save()
        if out_mp4.exists():
            out_mp4.unlink()
        pres.CreateVideo(str(out_mp4.resolve()), True, 15, 1080, 30, 85)
        deadline = time.time() + 240.0
        while time.time() < deadline:
            status = pres.CreateVideoStatus
            # 1=InProgress, 2=Queued, 3=Done, 4=Failed
            if status == 3:
                break
            if status == 4:
                raise RuntimeError("PowerPoint CreateVideo returned status 4 (Failed)")
            time.sleep(1.5)
        if not out_mp4.exists():
            raise RuntimeError("Demo MP4 was not created before timeout")
    finally:
        pres.Close()
        ppt.Quit()

    if SCRATCH_STORYBOARD.exists():
        SCRATCH_STORYBOARD.unlink()
    print(f"Exported Demo MP4: {out_mp4} ({out_mp4.stat().st_size:,} bytes, planned duration={sum(durations)}s)")
    return out_mp4


def main() -> None:
    build_presentation(
        REPO_ROOT / "4_DICTATOR_IS355_Final_Presentation.pptx",
        REPO_ROOT / "4_DICTATOR_IS355_Final_Presentation.pdf",
    )
    build_demo_video(REPO_ROOT / "demo" / "X-SPIDE-G_demo.mp4")


if __name__ == "__main__":
    main()
