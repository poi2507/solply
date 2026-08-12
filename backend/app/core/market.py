"""시세 구매 — 에이전트의 판단 재료를 x402로 사서 쓴다.

기본 출처(QUOTE_SOURCE=self)는 **우리 데이터 상점의 체결가 지수**다: 에이전트가
자기 지갑(devnet USDC)으로 402를 지불하고 산다 — 생태계가 만든 체결 데이터가
다시 판단 재료가 되는 자급 순환. 지수→가격→지수의 순환 참조는 fair_price의
±10% 밴드가 안정화한다. paysh 출처는 주최측 데모 디버거(샌드박스) 폴백이다.

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

import httpx

from app import config
from app.agents import utils
from app.core import protocol
from app.db import store as db
from app.solana import payments

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


# 제공자 표기 — 화면에 그대로 나가는 문구다.
# `mpp-demo`는 주최 측 결제 디버거의 데모 응답이라 **가격 자체는 의미가 없다**
# (같은 심볼이 몇 초 만에 153 → 131로 바뀌고, 없는 심볼에도 값을 만들어 준다).
# 원문 그대로 "제공 mpp-demo"라고 쓰면 보는 사람이 데모인 줄 모르므로 풀어 적는다.
# 실제 시세 피드를 붙이면 그 제공자 이름이 그대로 나온다.
PROVIDER_LABELS = {"mpp-demo": "pay.sh 데모 시세", "solply-index": "Solply 자체 체결가 지수"}


def _summary(symbol: str, price: float, prev: float | None, source: str) -> str:
    if prev:
        trend = f"직전 구매가 대비 {(price - prev) / prev * 100:+.1f}%"
    else:
        trend = "첫 조회 — 기준 시세로 기록"
    provider = PROVIDER_LABELS.get(source, source)
    return f"{symbol} {price} USD ({trend}, 제공 {provider})"


def quote(sku: str, actor: str, buyer: str | None = None) -> dict | None:
    """시세 한 건을 구매한다. TTL 내 재사용, 실패하면 직전 시세라도 돌려준다.

    PAYSH_ENABLED는 두 출처 공통의 킬 스위치다 (테스트·촬영 중 구매 차단).
    """
    if not config.PAYSH_ENABLED:
        return None
    if config.QUOTE_SOURCE == "self" and buyer:
        return _self_quote(sku, actor, buyer)
    if shutil.which(config.PAYSH_BIN) is None:
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


def _self_quote(sku: str, actor: str, buyer: str) -> dict | None:
    """우리 데이터 상점에서 체결가 지수를 산다 — 402 견적 → devnet 지불 → 인도.

    구매자는 에이전트 자신의 지갑이다. 어떤 실패도 조달을 멈추지 않는다는
    계약은 그대로: 실패하면 직전 지수, 그것도 없으면 None.
    """
    now = datetime.now(UTC)
    cached = db.get(QUOTES, sku)
    if cached:
        age = (now - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
        if age < config.PAYSH_QUOTE_TTL_S:
            return cached

    try:
        base = config.SOLPLY_API_URL
        challenge = httpx.get(f"{base}/x402/data/market/{sku}", timeout=15)
        if challenge.status_code != 402:
            return cached
        req = challenge.json()
        accept = req["accepts"][0]
        order_id = req["extensions"]["solply.dataOrder"]["id"]

        paid = payments.pay(buyer, accept["payTo"],
                            protocol.from_atomic(accept["amount"]), accept["extra"]["memo"])
        header = protocol.encode_header(
            {"x402Version": protocol.X402_VERSION, "payload": {"signature": paid["signature"]}}
        )
        settled = httpx.post(f"{base}{req['resource']['url']}",
                             headers={"PAYMENT-SIGNATURE": header}, timeout=30)
        body = settled.json()
        index = body.get("data") or {}
        unit = index.get("unit_price_usdc")
        if settled.status_code != 200 or unit is None:  # 검증 실패 또는 표본 없음
            print(f"[market] 자가 지수 구매 실패({settled.status_code}) — 직전 시세로 진행")
            return cached
        from app.core import stats
        stats.add_quote_flow(buyer, protocol.from_atomic(accept["amount"]))
    except Exception as exc:  # noqa: BLE001 — 시세가 조달을 멈출 사유는 아니다
        print(f"[market] 자가 지수 구매 불가 — 시세 없이 진행: {exc}")
        return cached

    prev = float(cached["price_usd"]) if cached else None
    # price_usd 키는 fair_price 호환용 — 자가 지수의 단위는 USDC다
    doc = db.put(QUOTES, sku, {
        "symbol": sku,
        "price_usd": float(unit),
        "prev_price_usd": prev,
        "source": "solply-index",
        "samples": index.get("samples"),
        "summary": _summary(sku, float(unit), prev, "solply-index"),
        "receipt": {"reference": (body.get("receipt") or {}).get("transaction", ""),
                    "explorer": (body.get("receipt") or {}).get("explorer", "")},
        "fetched_at": now.isoformat(),
    })
    utils.log(actor, "market.quote_purchased", {
        "sku": sku,
        "price_usd": float(unit),
        "samples": index.get("samples"),
        "source": "solply-index",
        "paid_via": "x402 (자가 지수 · devnet)",
        "receipt_ref": (body.get("receipt") or {}).get("transaction", ""),
        "order_id": order_id,
    })
    return doc
