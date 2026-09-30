"""가짜 결제 서비스 — 평가용 경제를 devnet 지갑을 건드리지 않고 돌린다.

payments/(TypeScript)와 같은 세 엔드포인트만 흉내 낸다: /balance/{w}, /pay, /tx/{sig}.
잔액은 메모리 장부로 움직인다 — 잔액이 모자라면 결제가 실패해 유예·분할 협상이 자연히 생긴다.
"""

import secrets

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()
# 지점 잔액을 일부러 엇갈리게 — A는 넉넉, B·C는 빠듯해 협상이 갈리게 한다
START = {"hq": 300.0, "store-a": 60.0, "store-b": 9.0, "store-c": 5.0,
         "guest": 500.0, "trader": 50.0, "escrow": 0.0}
BAL = dict(START)
ADDR = {w: f"FAKE{w.upper().replace('-', '')}{'1' * (40 - len(w))}"[:44] for w in START}
BY_ADDR = {a: w for w, a in ADDR.items()}
TXS: dict[str, dict] = {}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/balance/{wallet}")
def balance(wallet: str):
    if wallet not in BAL:
        raise HTTPException(400, f"unknown wallet {wallet}")
    return {"wallet": wallet, "address": ADDR[wallet], "sol": 1.0, "usdc": round(BAL[wallet], 6)}


class Pay(BaseModel):
    model_config = {"populate_by_name": True}
    frm: str = ""
    recipient: str
    amount: float
    memo: str = ""


@app.post("/pay")
def pay(body: dict):
    frm, to, amount, memo = body.get("from"), body.get("recipient"), float(body.get("amount", 0)), body.get("memo", "")
    if frm not in BAL:
        raise HTTPException(400, "bad from")
    if BAL[frm] + 1e-9 < amount:
        raise HTTPException(500, f"insufficient funds: {frm} has {BAL[frm]:.2f}, needs {amount:.2f}")
    BAL[frm] -= amount
    if to in BY_ADDR:
        BAL[BY_ADDR[to]] += amount
    sig = "FAKE" + secrets.token_hex(40)
    TXS[sig] = {"found": True, "signature": sig, "success": True, "memo": memo, "feePayer": ADDR["hq"],
                "transfer": {"source": ADDR[frm], "destination": to, "amount": amount},
                "explorer": f"fake://{sig}"}
    return {"status": "confirmed", "signature": sig, "from": ADDR[frm], "recipient": to,
            "amount": amount, "memo": memo, "feePayer": "hq", "explorer": f"fake://{sig}"}


@app.get("/tx/{sig}")
def tx(sig: str):
    if sig not in TXS:
        raise HTTPException(404, "not found")
    return TXS[sig]
