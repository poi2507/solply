"""On-chain payment check — never trust what the client says it paid.

A browser wallet signs a transfer and hands back a signature. Before you release goods, read that
transaction from the chain and compare five things against what *you* expected:

  1. it succeeded
  2. the tokens landed in your token account (not the payer's other account, not someone else's)
  3. the amount is exactly the order total
  4. the memo carries this order's id (so one payment cannot be claimed by two orders)
  5. the fee payer is the wallet that placed the order (it was signed by that customer)

`parse_transaction` turns a Solana RPC `getTransaction` result (encoding "jsonParsed") into the small
`Observed` shape; `verify_payment` compares it. Keep a record of accepted signatures and refuse
one that already paid for a different order — `verify_payment` cannot see your database.
"""

from dataclasses import dataclass, field

MEMO_PROGRAMS = {"spl-memo"}
TOKEN_PROGRAMS = {"spl-token", "spl-token-2022"}


@dataclass(frozen=True)
class Expected:
    destination: str      # your token account (e.g. the merchant's USDC ATA)
    amount: float         # in UI units (1.5 = 1.5 USDC)
    memo: str             # the order id
    payer: str            # the wallet that placed the order
    mint: str | None = None


@dataclass(frozen=True)
class Observed:
    success: bool
    destination: str | None
    amount: float | None
    memo: str | None
    fee_payer: str | None
    mint: str | None = None


@dataclass(frozen=True)
class Check:
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def verify_payment(observed: Observed, expected: Expected, *, tolerance: float = 1e-6) -> Check:
    problems = []
    if not observed.success:
        problems.append("the transaction failed on-chain")
    if observed.destination != expected.destination:
        problems.append("it was not sent to the expected token account")
    if expected.mint and observed.mint and observed.mint != expected.mint:
        problems.append("it moved a different token")
    if observed.amount is None or abs(observed.amount - expected.amount) > tolerance:
        problems.append(f"amount {observed.amount} does not match {expected.amount}")
    if expected.memo not in (observed.memo or ""):
        problems.append("the memo does not carry this order id")
    if observed.fee_payer != expected.payer:
        problems.append("it was not signed and paid by the wallet that placed the order")
    return Check(problems)


def _instructions(tx: dict) -> list[dict]:
    out = list(tx.get("transaction", {}).get("message", {}).get("instructions", []))
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        out.extend(inner.get("instructions", []))
    return out


def parse_transaction(tx: dict, *, decimals: int = 6) -> Observed:
    """Read an RPC `getTransaction(sig, {"encoding": "jsonParsed"})` result.

    Takes the first SPL token transfer and the memo. `decimals` is used only for a plain `transfer`
    (raw base units); `transferChecked` carries its own decimals.
    """
    meta = tx.get("meta") or {}
    keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    first = keys[0] if keys else None
    fee_payer = first.get("pubkey") if isinstance(first, dict) else first

    destination = amount = memo = mint = None
    for ix in _instructions(tx):
        program = ix.get("program")
        parsed = ix.get("parsed")
        if program in MEMO_PROGRAMS and memo is None:
            memo = parsed if isinstance(parsed, str) else None
        elif program in TOKEN_PROGRAMS and isinstance(parsed, dict) and destination is None:
            kind, info = parsed.get("type"), parsed.get("info", {})
            if kind == "transferChecked":
                destination, mint = info.get("destination"), info.get("mint")
                amount = float(info.get("tokenAmount", {}).get("uiAmountString") or 0)
            elif kind == "transfer":
                destination = info.get("destination")
                amount = int(info.get("amount", 0)) / 10 ** decimals
    return Observed(success=meta.get("err") is None, destination=destination, amount=amount,
                    memo=memo, fee_payer=fee_payer, mint=mint)
