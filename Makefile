PYTHON ?= python

.PHONY: help install phase1 phase2 phase3 phase4 phase4-xai phase5-test phase6-demo phase7-e5-offline phase8-trace verify clean-clone-e1 test dapp

help:
	@echo "X-SPIDE-G Reproducibility Targets:"
	@echo "  make install           Install pinned dependencies from requirements.txt"
	@echo "  make verify            Non-destructive verification of data, E1, contracts, E5 gas & traceability"
	@echo "  make clean-clone-e1    Bootstrap raw data (if absent), rebuild Phase 1, verify E1 + contract tests"
	@echo "  make test              Run full pytest suite"
	@echo "  make phase1            Download manifest data & run Phase 1 audit/splits"
	@echo "  make phase2            Run Phase 2 E0/E1/E2 5x5 grouped CV & baseline_v1 card"
	@echo "  make phase3            Extract F-BIGRAM, F-GSTAT, F-GSEM features & timings"
	@echo "  make phase4            Run Phase 4 E3-E4d, sensitivity S1-S4, E6 & stats"
	@echo "  make phase4-xai        Generate SHAP, CFG, and error analysis outputs"
	@echo "  make phase5-test       Run smart contract verification suite (T1-T12) with coverage"
	@echo "  make phase6-demo       Run CLI Anvil E2E evidence + tamper verification demo"
	@echo "  make phase7-e5-offline Run offline Anvil E5 benchmark (overwrites local CSV/JSON)"
	@echo "  make phase8-trace      Regenerate traceability_matrix.{csv,md}"
	@echo "  make dapp              Launch Streamlit 4-page DApp + static signer + PyEVM Anvil RPC"

install:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e . --no-deps

phase1:
	$(PYTHON) -m src.data.download
	$(PYTHON) -m src.data.pipeline --skip-rpc

phase2:
	$(PYTHON) -m src.models.run_phase2

phase3:
	$(PYTHON) -m src.features.pipeline

phase4:
	$(PYTHON) -m src.models.run_phase4_experiments

phase4-xai:
	$(PYTHON) -m src.models.phase4_xai

phase5-test:
	$(PYTHON) -m pytest tests/contracts --cov=src/contracts --cov-report=term-missing -v

phase6-demo:
	$(PYTHON) -m scripts.run_phase6_e2e_demo

phase7-e5-offline:
	$(PYTHON) -m scripts.run_phase7_e5 --skip-live

phase8-trace:
	$(PYTHON) -m scripts.build_phase8_traceability

verify:
	$(PYTHON) -m scripts.run_all --mode verify

clean-clone-e1:
	$(PYTHON) -m scripts.run_all --mode clean-clone

test:
	$(PYTHON) -m pytest -v

dapp:
	$(PYTHON) -m scripts.run_dapp --with-anvil-rpc
