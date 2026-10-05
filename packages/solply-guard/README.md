# solply-guard

Guardrails for AI agents that hold a wallet.

When an agent can move money by itself, the model should decide *whether* to pay. Code that a
person configures should decide whether it *may*. `solply-guard` is that code, extracted from
[Solply](https://github.com/poi2507/solply), where agents settle franchise supply payments in USDC on Solana.

It has no dependencies. Bring your own wallet, RPC client and model.

## Three guards

### 1. Spend guard: may the agent pay this on its own?

```python
from solply_guard import SpendPolicy, check_spend, Verdict

policy = SpendPolicy(auto_pay_limit=10, min_reserve=2)    # set by the wallet's owner, not the model

d = check_spend(12, policy, balance=50)
d.verdict            # Verdict.NEEDS_HUMAN — over the limit; park it for a person
check_spend(9, policy, balance=10).verdict               # Verdict.BREAKS_RESERVE — would leave 1 < 2
check_spend(12, policy, balance=50, human_approved=True).allowed   # True — a person lifted the limit
```

A person's approval lifts only the limit. It cannot make an empty wallet pay, and it cannot
break the reserve.

### 2. On-chain payment check: did the customer really pay?

A browser wallet signs a transfer and sends back a signature. Before you release goods, read
that transaction from the chain and compare it with what *you* expected. Never compare it with
what the client claims.

```python
from solply_guard import Expected, parse_transaction, verify_payment

tx = rpc.get_transaction(signature, encoding="jsonParsed")   # any Solana RPC client
check = verify_payment(parse_transaction(tx), Expected(
    destination=MERCHANT_USDC_ACCOUNT,   # your token account
    amount=order.total,                  # exact total
    memo=order.id,                       # ties the payment to one order
    payer=order.wallet,                  # the wallet that placed the order
))
check.ok, check.problems   # each mismatch is named: amount, memo, account, signer, failure
```

The five checks are: the transaction succeeded, it went to your account, the amount matches,
the memo carries the order id, and the fee payer is the ordering wallet. Also keep the
signatures you have accepted, and refuse one that already paid for a different order. That
check lives in your database, so this library cannot do it for you.

### 3. Confidence gate: may a fast decision stand without a second look?

Some decision models score a fixed set of options and return a confidence: System One models,
such as TypeSafe's Jev. Accept such a choice only when it clears a bar a person set. Otherwise,
send the decision to the slow path: an LLM that reasons from scratch, or a person.

```python
from solply_guard import route

r = route(answer.choice, answer.confidence, min_confidence_pct=70,
          allowed={"accept", "reject"},
          always_slow={"accept"})      # e.g. accepting also needs picking a candidate
r.fast, r.reason                       # False, "confidence 44% is under 70%"
```

Setting the bar to 100 turns the fast path off.

## How Solply uses it

| Guard | Where in Solply |
|---|---|
| Spend guard | A store agent paying an HQ invoice or a peer trade, under limits the owner sets on the dashboard |
| On-chain check | A visitor paying from their own Phantom wallet. Goods are sold only after the five checks pass |
| Confidence gate | Jev decides routine calls (restock route, order review); low-confidence ones go to Gemini |

The on-chain test runs against a real devnet payment (`tests/fixtures/devnet_usdc_payment.json`):
a visitor paying 2.43 USDC for order `ORD-0924-Aa16b`.

## Install and test

```bash
pip install "git+https://github.com/poi2507/solply#subdirectory=packages/solply-guard"
# or, from a clone
cd packages/solply-guard && uv run --with pytest python -m pytest
```

Python 3.11+. MIT licensed.
