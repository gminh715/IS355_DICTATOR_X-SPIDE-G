"""Reproducibility & end-to-end verification runner for X-SPIDE-G."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cmd(cmd: list[str], *, cwd: Path) -> None:
    print(f">>> {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def verify_e1_reproduction(repo_root: Path, *, refit_fold0: bool = True) -> dict[str, Any]:
    """Re-evaluate frozen E1 baseline_v1 and optionally re-fit E1 fold0 from splits/."""
    import joblib
    from src.models.data_prep import load_contracts_dataset, load_split_indices, prepare_xspide_99_features
    from src.models.metrics import evaluate_predictions
    from src.models.tuning import make_pipeline_from_params

    card_path = repo_root / "models" / "baseline_v1" / "model_card.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    split_name = str(card["dataset"]["demo_split"])
    split_path = repo_root / "splits" / split_name

    df_code = load_contracts_dataset(repo_root, subset="S_code")
    X_99 = prepare_xspide_99_features(df_code)
    assert X_99.shape[1] == 99, f"Expected 99 features, got {X_99.shape[1]}"

    tr_idx, te_idx, _ = load_split_indices(df_code, split_path)
    y = df_code["label"].to_numpy(dtype=int)
    tau = float(card["classification_threshold"])

    pipe = joblib.load(repo_root / card["artifacts"]["model_file"])
    proba = pipe.predict_proba(X_99.iloc[te_idx])[:, 1]
    eval_frozen = evaluate_predictions(y[te_idx], proba, threshold=tau)

    expected_pr_auc = float(card["demo_fold_metrics"]["pr_auc"])
    assert abs(eval_frozen["pr_auc"] - expected_pr_auc) < 1e-6, (
        f"Frozen E1 PR-AUC mismatch: {eval_frozen['pr_auc']} vs {expected_pr_auc}"
    )

    out: dict[str, Any] = {
        "split": split_name,
        "n_train": int(len(tr_idx)),
        "n_test": int(len(te_idx)),
        "frozen_pr_auc": float(eval_frozen["pr_auc"]),
        "frozen_f1": float(eval_frozen["f1"]),
        "expected_pr_auc": expected_pr_auc,
        "matches_model_card": True,
    }

    if refit_fold0:
        fresh_pipe = make_pipeline_from_params(
            dict(card["hyperparameters"]),
            random_state=42,
            n_jobs=4,
            use_rfe=False,
        )
        fresh_pipe.fit(X_99.iloc[tr_idx], y[tr_idx])
        fresh_proba = fresh_pipe.predict_proba(X_99.iloc[te_idx])[:, 1]
        eval_fresh = evaluate_predictions(y[te_idx], fresh_proba, threshold=tau)
        assert abs(eval_fresh["pr_auc"] - expected_pr_auc) < 1e-4, (
            f"Refit E1 PR-AUC diverged: {eval_fresh['pr_auc']} vs {expected_pr_auc}"
        )
        out["refit_fold0_pr_auc"] = float(eval_fresh["pr_auc"])
        out["refit_fold0_f1"] = float(eval_fresh["f1"])
        out["max_abs_proba_diff"] = float(np.max(np.abs(fresh_proba - proba)))

    return out


def verify_e5_anvil_determinism(repo_root: Path) -> dict[str, Any]:
    """Verify deterministic Cancun PyEVM gas measurements match results/E5_gas.csv."""
    from src.contracts.e5_benchmark import run_anvil_gas_suite

    gas_df = pd.read_csv(repo_root / "results" / "E5_gas.csv")
    recorded = gas_df[
        (gas_df["network"] == "anvil_pyevm") & (gas_df["variant"] == "D1") & (gas_df["operation"] == "finalized_case_total")
    ].iloc[0]
    expected_d1_total = int(float(recorded["gas_used"]))

    rows = run_anvil_gas_suite()
    d1_row = next(r for r in rows if r["variant"] == "D1" and r["operation"] == "finalized_case_total")
    d3_100 = next(r for r in rows if r["variant"] == "D3" and r["operation"] == "batch_finalized_total" and r["batch_size"] == 100)
    assert int(d1_row["gas_used"]) == expected_d1_total, f"D1 gas mismatch: {d1_row['gas_used']} vs {expected_d1_total}"
    return {
        "d1_finalized_case_total_gas": int(d1_row["gas_used"]),
        "d3_batch100_gas_per_case": float(d3_100["gas_per_case"]),
        "matches_e5_gas_csv": True,
    }


def ensure_clean_clone_data(repo_root: Path) -> None:
    """Download pinned raw datasets and build data/processed/contracts.parquet if missing."""
    parquet_path = repo_root / "data" / "processed" / "contracts.parquet"
    if parquet_path.exists():
        print(f"Found existing processed dataset: {parquet_path}", flush=True)
        return

    from src.data.download import verify_manifest

    manifest_path = repo_root / "data" / "manifest.json"
    expected_xspide = repo_root / "data" / "raw" / "x-spide" / "dataset" / "DS_deployed_bytecode.csv"
    if not expected_xspide.exists():
        print("Bootstrapping public raw datasets specified in data/manifest.json...", flush=True)
        orig_manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else None
        from src.data.download import run_download

        run_download(repo_root, force=False)
        if orig_manifest is not None:
            # Verify downloaded files match the pinned committed manifest hashes without altering git diff
            manifest_path.write_text(orig_manifest, encoding="utf-8")
    verify_manifest(repo_root)
    _run_cmd([sys.executable, "-m", "src.data.pipeline", "--skip-rpc"], cwd=repo_root)


def run_verify_mode(repo_root: Path, *, refit_fold0: bool = True) -> dict[str, Any]:
    """Non-destructive end-to-end verification against committed artifacts and test suite."""
    if not (repo_root / "data" / "processed" / "contracts.parquet").exists():
        ensure_clean_clone_data(repo_root)

    e1_info = verify_e1_reproduction(repo_root, refit_fold0=refit_fold0)
    print(f"[E1 Reproduction] {json.dumps(e1_info)}", flush=True)

    e5_info = verify_e5_anvil_determinism(repo_root)
    print(f"[E5 Anvil Determinism] {json.dumps(e5_info)}", flush=True)

    _run_cmd([sys.executable, "-m", "pytest", "tests/contracts", "tests/evidence", "tests/test_phase8_deliverables.py", "-v"], cwd=repo_root)
    return {"e1": e1_info, "e5": e5_info}


def run_full_mode(repo_root: Path, *, skip_live_e5: bool = True) -> None:
    """Execute Phases 1 through 8 pipelines sequentially."""
    ensure_clean_clone_data(repo_root)
    _run_cmd([sys.executable, "-m", "src.models.run_phase2"], cwd=repo_root)
    _run_cmd([sys.executable, "-m", "src.features.pipeline"], cwd=repo_root)
    _run_cmd([sys.executable, "-m", "src.models.run_phase4_experiments"], cwd=repo_root)
    _run_cmd([sys.executable, "-m", "src.models.phase4_xai"], cwd=repo_root)
    _run_cmd([sys.executable, "-m", "pytest", "tests/contracts", "-v"], cwd=repo_root)
    _run_cmd([sys.executable, "-m", "scripts.run_phase6_e2e_demo"], cwd=repo_root)
    e5_cmd = [sys.executable, "-m", "scripts.run_phase7_e5"]
    if skip_live_e5:
        e5_cmd.append("--skip-live")
    _run_cmd(e5_cmd, cwd=repo_root)
    _run_cmd([sys.executable, "-m", "scripts.build_phase8_traceability"], cwd=repo_root)


def main() -> None:
    parser = argparse.ArgumentParser(description="X-SPIDE-G Phase 8 unified reproducibility runner.")
    parser.add_argument(
        "--mode",
        choices=["verify", "clean-clone", "e1-repro", "full"],
        default="verify",
        help="Execution mode: verify (non-destructive), clean-clone (bootstrap + E1 + contract tests), e1-repro, or full.",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--run-live-e5", action="store_true", help="Include live testnet txs during --mode full.")
    parser.add_argument("--no-refit", action="store_true", help="Skip E1 fold-0 model refit check.")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    if args.mode == "verify":
        run_verify_mode(root, refit_fold0=not args.no_refit)
    elif args.mode == "clean-clone":
        ensure_clean_clone_data(root)
        info = verify_e1_reproduction(root, refit_fold0=True)
        print(f"[Clean-Clone E1 Verification] {json.dumps(info)}", flush=True)
        _run_cmd([sys.executable, "-m", "pytest", "tests/contracts", "tests/evidence", "-v"], cwd=root)
    elif args.mode == "e1-repro":
        info = verify_e1_reproduction(root, refit_fold0=True)
        print(json.dumps(info, indent=2), flush=True)
    elif args.mode == "full":
        run_full_mode(root, skip_live_e5=not args.run_live_e5)


if __name__ == "__main__":
    main()
