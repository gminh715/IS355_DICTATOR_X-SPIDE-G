"""T11 Hypothesis property/fuzz test comparing RiskAttestationRegistry against Python reference."""

from __future__ import annotations

from eth_utils import keccak
from hypothesis import given, settings
from hypothesis import strategies as st
from eth_tester import EthereumTester, PyEVMBackend
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider

from src.contracts.compiler import compile_contract
from src.contracts.reference import (
    DECISION_NEEDS_REVIEW,
    DECISION_REJECT,
    STATUS_OPEN,
    STATUS_REJECTED,
    ReferenceRegistryState,
    compute_status,
)
from tests.contracts.conftest import ZERO_ADDRESS, ZERO_BYTES32, assert_reverts

OP_ADD_AUDITOR = "add_auditor"
OP_REMOVE_AUDITOR = "remove_auditor"
OP_SET_THRESHOLD = "set_threshold"
OP_REGISTER_CASE = "register_case"
OP_ATTEST = "attest"

op_strategy = st.lists(
    st.one_of(
        st.tuples(st.just(OP_ADD_AUDITOR), st.integers(0, 4), st.integers(0, 4)),
        st.tuples(st.just(OP_REMOVE_AUDITOR), st.integers(0, 4), st.integers(0, 4)),
        st.tuples(st.just(OP_SET_THRESHOLD), st.integers(0, 4), st.integers(0, 5)),
        st.tuples(st.just(OP_REGISTER_CASE), st.integers(0, 4), st.integers(0, 2)),
        st.tuples(st.just(OP_ATTEST), st.integers(0, 4), st.integers(0, 2), st.integers(0, 4)),
    ),
    min_size=12,
    max_size=24,
)


@settings(max_examples=25, deadline=None)
@given(ops=op_strategy)
def test_t11_property_fuzz_state_and_invariants(ops: list[tuple[int | str, ...]]) -> None:
    """T11: Under arbitrary action sequences, EVM state, tally sum, and status match Python spec."""
    w3 = Web3(EthereumTesterProvider(EthereumTester(PyEVMBackend())))
    accounts = w3.eth.accounts
    owner = accounts[0]
    actors = list(accounts[:5])  # [owner, cand1, cand2, cand3, outsider]
    subject = accounts[6]

    compiled = compile_contract("D1", use_cache=True)
    factory = w3.eth.contract(abi=compiled.abi, bytecode=compiled.bytecode)
    rc = w3.eth.wait_for_transaction_receipt(factory.constructor(ZERO_ADDRESS).transact({"from": owner}))
    contract = w3.eth.contract(address=rc.contractAddress, abi=compiled.abi)

    ref = ReferenceRegistryState(owner=owner, threshold=2)
    # Seed initial active auditors so register/attest steps fire frequently in random traces.
    for aud in actors[1:4]:
        w3.eth.wait_for_transaction_receipt(contract.functions.add_auditor(aud).transact({"from": owner}))
        ref.add_auditor(owner, aud)

    case_ids = [keccak(f"fuzz-case-{i}".encode()) for i in range(3)]
    ev_hashes = [keccak(f"fuzz-ev-{i}".encode()) for i in range(3)]
    model_hash = keccak(b"fuzz-model-v1")

    for step in ops:
        op = step[0]
        if op == OP_ADD_AUDITOR:
            caller = actors[step[1]]
            target = actors[step[2]]
            try:
                ref.add_auditor(caller, target)
            except ValueError as err:
                assert_reverts(
                    lambda: w3.eth.wait_for_transaction_receipt(
                        contract.functions.add_auditor(target).transact({"from": caller})
                    ),
                    str(err),
                )
            else:
                w3.eth.wait_for_transaction_receipt(
                    contract.functions.add_auditor(target).transact({"from": caller})
                )

        elif op == OP_REMOVE_AUDITOR:
            caller = actors[step[1]]
            target = actors[step[2]]
            try:
                ref.remove_auditor(caller, target)
            except ValueError as err:
                assert_reverts(
                    lambda: w3.eth.wait_for_transaction_receipt(
                        contract.functions.remove_auditor(target).transact({"from": caller})
                    ),
                    str(err),
                )
            else:
                w3.eth.wait_for_transaction_receipt(
                    contract.functions.remove_auditor(target).transact({"from": caller})
                )

        elif op == OP_SET_THRESHOLD:
            caller = actors[step[1]]
            k = int(step[2])
            try:
                ref.set_threshold(caller, k)
            except ValueError as err:
                assert_reverts(
                    lambda: w3.eth.wait_for_transaction_receipt(
                        contract.functions.set_threshold(k).transact({"from": caller})
                    ),
                    str(err),
                )
            else:
                w3.eth.wait_for_transaction_receipt(
                    contract.functions.set_threshold(k).transact({"from": caller})
                )

        elif op == OP_REGISTER_CASE:
            caller = actors[step[1]]
            idx = int(step[2])
            cid = case_ids[idx]
            eh = ev_hashes[idx]
            try:
                ref.register_case(caller, cid, subject, 1, eh, model_hash)
            except ValueError as err:
                assert_reverts(
                    lambda: w3.eth.wait_for_transaction_receipt(
                        contract.functions.register_case(cid, subject, 1, eh, model_hash, "ipfs://fuzz").transact(
                            {"from": caller}
                        )
                    ),
                    str(err),
                )
            else:
                w3.eth.wait_for_transaction_receipt(
                    contract.functions.register_case(cid, subject, 1, eh, model_hash, "ipfs://fuzz").transact(
                        {"from": caller}
                    )
                )

        elif op == OP_ATTEST:
            caller = actors[step[1]]
            cid = case_ids[int(step[2])]
            decision = int(step[3])
            try:
                ref.attest(caller, cid, decision)
            except ValueError as err:
                assert_reverts(
                    lambda: w3.eth.wait_for_transaction_receipt(
                        contract.functions.attest(cid, decision, ZERO_BYTES32).transact({"from": caller})
                    ),
                    str(err),
                )
            else:
                w3.eth.wait_for_transaction_receipt(
                    contract.functions.attest(cid, decision, ZERO_BYTES32).transact({"from": caller})
                )

        # Verify global governance parity after every step
        assert contract.functions.auditor_count().call() == ref.auditor_count
        assert contract.functions.threshold().call() == ref.threshold

        # Verify per-case invariants: tally sum == non-zero auditor attestations & status == compute_status(...)
        for cid, ref_case in ref.cases.items():
            ref.assert_invariants(cid)
            onchain_case = contract.functions.get_case(cid).call()
            approve_c, reject_c, review_c, status_c = onchain_case[6], onchain_case[7], onchain_case[8], onchain_case[9]

            non_zero_onchain = sum(
                1 for actor in actors if contract.functions.get_attestation(cid, actor).call()[0] != 0
            )
            assert approve_c + reject_c + review_c == non_zero_onchain
            assert (approve_c, reject_c, review_c) == (
                ref_case.approve_count,
                ref_case.reject_count,
                ref_case.review_count,
            )
            assert status_c == compute_status(approve_c, reject_c, ref_case.last_eval_threshold)
            assert status_c == ref_case.status


def test_t11_set_threshold_recomputation_deferral_matches_spec() -> None:
    """Regression check for Hypothesis seed where set_threshold follows attest without re-attesting."""
    w3 = Web3(EthereumTesterProvider(EthereumTester(PyEVMBackend())))
    accounts = w3.eth.accounts
    owner, aud0, aud1, aud2, subject = accounts[0], accounts[1], accounts[2], accounts[3], accounts[6]

    compiled = compile_contract("D1", use_cache=True)
    factory = w3.eth.contract(abi=compiled.abi, bytecode=compiled.bytecode)
    rc = w3.eth.wait_for_transaction_receipt(factory.constructor(ZERO_ADDRESS).transact({"from": owner}))
    contract = w3.eth.contract(address=rc.contractAddress, abi=compiled.abi)

    ref = ReferenceRegistryState(owner=owner, threshold=2)
    for aud in (aud0, aud1, aud2):
        w3.eth.wait_for_transaction_receipt(contract.functions.add_auditor(aud).transact({"from": owner}))
        ref.add_auditor(owner, aud)

    cid = keccak(b"threshold-deferral-case")
    eh = keccak(b"threshold-deferral-ev")
    mh = keccak(b"threshold-deferral-model")
    w3.eth.wait_for_transaction_receipt(
        contract.functions.register_case(cid, subject, 1, eh, mh, "ipfs://reg").transact({"from": aud0})
    )
    ref.register_case(aud0, cid, subject, 1, eh, mh)

    # Reject count=1 at threshold=2 keeps case Open
    w3.eth.wait_for_transaction_receipt(
        contract.functions.attest(cid, DECISION_REJECT, ZERO_BYTES32).transact({"from": aud0})
    )
    ref.attest(aud0, cid, DECISION_REJECT)

    # Lower threshold to 1: stored case.status remains Open until next attest triggers _compute_status
    w3.eth.wait_for_transaction_receipt(contract.functions.set_threshold(1).transact({"from": owner}))
    ref.set_threshold(owner, 1)
    ref.assert_invariants(cid)
    assert contract.functions.get_case(cid).call()[9] == STATUS_OPEN == ref.cases[cid].status

    # Subsequent attest recomputes case status under threshold=1 -> Rejected
    w3.eth.wait_for_transaction_receipt(
        contract.functions.attest(cid, DECISION_NEEDS_REVIEW, ZERO_BYTES32).transact({"from": aud1})
    )
    ref.attest(aud1, cid, DECISION_NEEDS_REVIEW)
    ref.assert_invariants(cid)
    assert contract.functions.get_case(cid).call()[9] == STATUS_REJECTED == ref.cases[cid].status
