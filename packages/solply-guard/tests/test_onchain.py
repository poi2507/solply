"""Parsed against a real devnet transaction: a visitor paid 2.43 USDC for order ORD-0924-Aa16b."""

import json
from dataclasses import replace
from pathlib import Path

from solply_guard import Expected, parse_transaction, verify_payment

TX = json.loads((Path(__file__).parent / "fixtures" / "devnet_usdc_payment.json").read_text())
EXPECTED = Expected(destination="5F6BepncKQ5b2chBdmuFWx2muBzYGxfuit3xPggwKruB", amount=2.43,
                    memo="ORD-0924-Aa16b", payer="5BJB4uHwemJpE2G1c1JcDzHpv1abrtQBhjEFacby9cWh")


def test_parses_real_devnet_payment():
    o = parse_transaction(TX)
    assert o.success and o.amount == 2.43 and o.memo == "ORD-0924-Aa16b"
    assert o.destination == EXPECTED.destination and o.fee_payer == EXPECTED.payer


def test_real_payment_verifies():
    assert verify_payment(parse_transaction(TX), EXPECTED).ok


def test_each_mismatch_is_named():
    o = parse_transaction(TX)
    cases = {
        "amount": replace(EXPECTED, amount=2.44),
        "memo": replace(EXPECTED, memo="ORD-OTHER"),
        "token account": replace(EXPECTED, destination="SomeoneElse111"),
        "signed and paid": replace(EXPECTED, payer="AnotherWallet111"),
    }
    for word, exp in cases.items():
        check = verify_payment(o, exp)
        assert not check.ok and len(check.problems) == 1 and word in check.problems[0], word


def test_failed_transaction_is_rejected():
    failed = {**TX, "meta": {**TX["meta"], "err": {"InstructionError": [0, "Custom"]}}}
    assert "failed" in verify_payment(parse_transaction(failed), EXPECTED).problems[0]


def test_transfer_checked_shape():
    tx = {"meta": {"err": None}, "transaction": {"message": {
        "accountKeys": [{"pubkey": "Payer1"}],
        "instructions": [
            {"program": "spl-token", "parsed": {"type": "transferChecked", "info": {
                "destination": "Dest1", "mint": "Mint1", "tokenAmount": {"uiAmountString": "1.5"}}}},
            {"program": "spl-memo", "parsed": "ORD-1"}]}}}
    o = parse_transaction(tx)
    assert (o.amount, o.mint, o.memo, o.fee_payer) == (1.5, "Mint1", "ORD-1", "Payer1")
    assert not verify_payment(o, Expected("Dest1", 1.5, "ORD-1", "Payer1", mint="Mint2")).ok
