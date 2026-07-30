"""시세 구매 — 에이전트의 판단 재료를 pay.sh(x402)로 사서 쓴다.

무료 크롤링이 아니라 유료 데이터다. `pay --sandbox curl`이 402 챌린지를 만나
스스로 지불하고, 응답의 payment-receipt(온체인 참조 포함)를 증빙으로 남긴다.
샌드박스(호스티드 Surfpool 로컬넷)에서 지갑이 자동 생성·충전되므로 실자금은 없다.

같은 심볼은 TTL 동안 재사용한다 — 시세는 분 단위로 변하지 않고,
조달 한 바퀴(틱)에 같은 데이터를 두 번 사는 건 낭비다.
"""

import base64
import json
import shutil
import subprocess
from datetime import UTC, datetime

from app import config
from app.agents import utils
from app.db import store as db

QUOTES = "market_quotes"


def _symbol(sku: str) -> str:
    """SKU에서 시세 심볼을 만든다 — CHK-10 → CHK."""
    return sku.split("-")[0]


def _parse(raw: str) -> tuple[dict | None, dict | None]:
    """pay curl -si 출력에서 (시세 본문, 결제 영수증)을 꺼낸다.

    출력에는 헤더·지갑 생성 이벤트 줄이 섞일 수 있어, 본문은 뒤에서부터
    price 필드를 가진 JSON 줄을 찾는다.
    """
    receipt = None
    body = None
    for line in raw.splitlines():
        if line.lower().startswith("payment-receipt:"):
            token = line.split(":", 1)[1].strip()
            try:
                receipt = json.loads(base64.b64decode(token + "=" * (-len(token) % 4)))
            except (ValueError, json.JSONDecodeError):
                receipt = None
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "price" in candidate:
            body = candidate
            break
    return body, receipt


def _summary(symbol: str, price: float, prev: float | None, source: str) -> str:
    if prev:
        trend = f"직전 구매가 대비 {(price - prev) / prev * 100:+.1f}%"
    else:
        trend = "첫 조회 — 기준 시세로 기록"
    return f"{symbol} {price} USD ({trend}, 제공 {source})"


def quote(sku: str, actor: str) -> dict | None:
    """시세 한 건을 구매한다. TTL 내 재사용, 실패하면 직전 시세라도 돌려준다."""
    if not config.PAYSH_ENABLED or shutil.which(config.PAYSH_BIN) is None:
        return None
    symbol = _symbol(sku)
    now = datetime.now(UTC)
    cached = db.get(QUOTES, symbol)
    if cached:
        age = (now - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
        if age < config.PAYSH_QUOTE_TTL_S:
            return cached

    try:
        proc = subprocess.run(
            [config.PAYSH_BIN, "--sandbox", "curl", "-si",
             f"{config.PAYSH_QUOTE_URL}/{symbol}"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[market] pay 실행 불가 — 시세 없이 진행: {exc}")
        return cached
    body, receipt = _parse(proc.stdout)
    if not body:
        # 조달은 계속 가지만, 원인은 서버 로그에 남긴다 (glibc·네트워크류 진단용)
        print(f"[market] 시세 구매 실패 (exit {proc.returncode}): {(proc.stderr or proc.stdout)[:200]}")
        return cached

    prev = float(cached["price_usd"]) if cached else None
    price = float(body["price"])
    source = body.get("source", "unknown")
    doc = db.put(QUOTES, symbol, {
        "symbol": symbol,
        "price_usd": price,
        "prev_price_usd": prev,
        "source": source,
        "summary": _summary(symbol, price, prev, source),
        "receipt": receipt,
        "fetched_at": now.isoformat(),
    })
    utils.log(actor, "market.quote_purchased", {
        "sku": sku,
        "symbol": symbol,
        "price_usd": price,
        "source": source,
        "paid_via": "pay.sh --sandbox (x402)",
        "receipt_ref": (receipt or {}).get("reference", ""),
    })
    return doc
