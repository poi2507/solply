"""빠른 판단 — TypeSafe Jev (System One 결정 모델).

LLM이 문장을 생성해 결론을 뽑는 대신, 선택지마다 확률을 매겨 하나를 고른다.
확신도(confidence)가 함께 오므로 "이 판단을 기계에 맡겨도 되는가"를 숫자로 가를 수 있다.

라이브에 넘긴 범위는 평가(scripts/jev_eval, 69건 Vertex 대비 96% 일치 — 확신도 0.5 이상은
전부 일치)로 확인한 판단 종류뿐이다. 나머지는 여기로 오지 않는다.
금액·수량은 여전히 코드가 계산한다 — Jev가 고르는 것은 선택지 하나뿐이다.
"""

import json
import re
import time
import urllib.error
import urllib.request

from app import config

URL = "https://api.typesafe.ai/v1/systemone"

# Jev는 영어가 1순위 — 한국어 사실 키를 옮긴다 (값은 그대로)
KEY_EN = {
    "품목": "item",
    "지점_일별판매_7일(과거→오늘)": "store_daily_sales_7d_oldest_to_today",
    "전국_일별판매_7일(해당 지점 제외)": "national_daily_sales_7d_excluding_this_store",
    "본사_창고_잔량": "hq_warehouse_stock",
    "후보 목록": "candidates",
    "이웃_지점": "neighbour_store",
    "본사_리드타임": "hq_lead_time",
    "본사_공급가_usdc": "hq_unit_price_usdc",
    "구매한_시세": "purchased_market_quote",
    "자기_소비_추세": "own_sales_trend",
    "원_주문_수량": "original_order_qty",
    "본사_축소_제안_수량": "hq_trimmed_qty",
    "본사_근거": "hq_reasoning",
    "자기_일별판매_7일(과거→오늘)": "own_daily_sales_7d_oldest_to_today",
}

# 일별 판매 시계열 → 요약. Jev는 세기·계산에 약하다(TypeSafe 문서) — 원자료는 그대로 두고
# 합계·판매일 수·최근 3일 대 이전 4일을 코드가 계산해 옆에 붙인다. 판정 자체는 하지 않는다.
SERIES_KEYS = {
    "지점_일별판매_7일(과거→오늘)": "store_sales_summary",
    "전국_일별판매_7일(해당 지점 제외)": "national_sales_summary",
    "자기_일별판매_7일(과거→오늘)": "own_sales_summary",
}


def sales_summary(series) -> dict | None:
    if not isinstance(series, list) or not series or not all(isinstance(x, (int, float)) for x in series):
        return None
    total = sum(series)
    last3, prev = sum(series[-3:]), sum(series[:-3])
    best = max(series)
    return {
        "total": total,
        "days_with_sales": f"{sum(1 for x in series if x > 0)} of {len(series)}",
        "last_3_days_vs_previous_4_days": f"{last3} vs {prev}",
        "best_single_day": best,
        "best_day_share_of_total_pct": round(best / total * 100) if total else 0,
    }

# 판단 종류별: 무엇을 묻는가 + 선택지별 경계 조건 (judge.py의 지시와 같은 뜻).
# TypeSafe 문서의 "literal reading" 주의 — 선택지마다 언제 고르는지를 문장으로 적는다.
QUESTIONS = {
    "adjustment": ("HQ reviews a store's request to deduct part of an invoice for a delivery mismatch.",
                   {"accept": "The delivery log supports the requested deduction and it is within the auto-approval limit",
                    "reject": "The request is not supported by the delivery log, or it is missing",
                    "counter": "Part of the claim is valid but a different amount should be offered"}),
    "deferral": ("HQ reviews a store's request to defer paying an invoice.",
                 {"accept": "Credit score meets the threshold and the deferred exposure is within the allowed share of the credit line",
                  "reject": "Credit score is below the threshold or the risk is too high",
                  "counter": "Creditworthy, but the deferred exposure is too large, so offer installments instead"}),
    "p2p_trade": ("HQ reviews a proposed peer trade of stock between two stores.",
                  {"accept": "Seller keeps its safety stock, both credit scores meet the threshold, and the price is within the HQ supply price",
                   "reject": "The seller would breach safety stock, or a credit score is below threshold",
                   "counter": "Otherwise fine, but the unit price is above the HQ supply price"}),
    "order": ("HQ reviews a store's restock order that is larger than the base quantity.",
              {"accept": "Sales rose over several days — the last 3 days clearly outsold the previous 4, "
                         "on more than one day — so the larger order matches real demand",
               "counter": "Sales are flat, sporadic or one day's spike — few days with sales, or one day "
                          "carries most of the week — so trim to the base quantity",
               "reject": "The order should not be fulfilled at all"}),
    "brokerage": ("HQ decides whether to broker one stock transfer between stores from the candidate list. "
                  "Brokering is optional every round; when in doubt, HQ does not broker.",
                  {"accept": "One candidate is clearly worth it: the short store is below its safety line now "
                             "and the surplus store keeps its own safety stock after giving",
                   "reject": "No candidate is clearly worth it this round, or it is a close call"}),
    "counter_response": ("A store replies to HQ's offer to split an invoice into installments.",
                         {"accept": "The store can afford each installment",
                          "counter": "Each installment is too heavy, but the store can pay part upfront",
                          "reject": "The store cannot even pay part upfront"}),
    "supply_route": ("A store chooses how to restock a short item.",
                     {"p2p": "A neighbour's surplus covers it today, avoiding HQ lead time or minimum order",
                      "hq": "Order from HQ: not enough neighbour surplus, or HQ terms are better"}),
    "order_adjust": ("A store replies to HQ's proposal to trim its restock order.",
                     {"accept": "Our own sales are flat, sporadic or one day's spike, so HQ's smaller quantity is enough",
                      "insist": "Our own sales rose over several days — the last 3 days clearly outsold the previous 4 — "
                                "so keep the original quantity"}),
    "p2p_respond": ("A selling store replies to a peer trade offer.",
                    {"accept": "Sell at the offered price",
                     "counter": "This item sells well here and spare stock is thin, so ask a higher price"}),
    "p2p_price": ("A buying store replies to the seller's higher counter price.",
                  {"accept": "Taking it today is still worth the higher price",
                   "hq": "At that price, ordering from HQ is better despite the lead time"}),
    "p2p_consider": ("A buying store replies to a peer trade that HQ brokered.",
                     {"accept": "Taking the partial quantity today helps; the rest can come from HQ",
                      "decline": "The brokered terms do not fit this store's situation"}),
}

# 라이브에서 Jev가 먼저 보는 판단 — 평가에서 전부 일치한 종류만.
# 발주 축소 응답(order_adjust)은 뺀다: 9/30 평가 11건 중 3건 불일치(확신도 낮음), 10/9 판매 요약을
# 붙인 재평가에선 확신도가 0.96~1.0으로 올랐지만 4건이 Vertex와 반대였다 — 지점 성향(persona)이
# 갈라 놓는 판단이라 확신 있게 틀리는 쪽이 더 위험하다. 표본이 없던 종류도 LLM이 계속 판단한다.
LIVE_KINDS = {"supply_route", "p2p_trade", "order", "brokerage"}

# Jev가 골라도 LLM으로 넘기는 선택 — 중개 수락은 "어느 후보"까지 골라야 하는데
# Jev 질문은 수락/거절만 묻는다. 거절(이번엔 중개 안 함)만 바로 확정한다.
NEEDS_SYSTEM_TWO = {("brokerage", "accept")}

# 코드가 만드는 한국어 값 → 영어. 화면에 보이는 원문(협상 기록·시세 요약)은 한국어로 두고
# (화면 번역은 i18n.js가 한다) Jev에 넣기 직전에만 옮긴다. 긴 구가 먼저 와야 한다.
VALUE_PATTERNS = [
    (r"\(안전재고 회복분 — 축소 제안의 바닥\)", "(restores safety stock — the floor for any trim)"),
    (r"(\d+)개 \(부족 지점 재고 (\d+)/(\d+), 필요 (\d+)개 중 부분\) 단가 ([\d.]+) USDC · 전국 일별 ",
     r"×\1 (short store stock \2 / safety line \3, partial of \4 needed) unit price \5 USDC · national daily "),
    (r"최근 (\d+)일 (\d+)개 판매", r"sold \2 in the last \1 days"),
    (r", 직전 창 대비 ([+-][\d.]+)%", r", \1% vs the previous window"),
    (r"직전 구매가 대비 ([+-][\d.]+)%", r"\1% vs the last purchased price"),
    (r"구매한 외부 시세: ", "purchased external quote: "),
    (r"본사 중개\(부분 잉여\) — ", "HQ-brokered (partial surplus) — "),
]
VALUE_WORDS = {
    ", 비교 기준 없음": ", no previous window to compare",
    " (자기 판매 원장)": " (own sales ledger)",
    "첫 조회 — 기준 시세로 기록": "first lookup — recorded as the baseline",
    " — pay.sh(x402) 결제": " — paid via pay.sh (x402)",
    "pay.sh 데모 시세": "pay.sh demo quote",
    "Solply 자체 체결가 지수": "Solply trade-price index",
    ", 제공 ": ", source: ",
    "판매 기록 없음": "no sales records",
    "제공 안 됨": "not provided",
    "미확인": "unknown",
    "없음": "none",
}


def _personas() -> dict[str, str]:
    """사정·기조 원문 → 영어판 (시드 프로필·프리셋·기본값). 점주가 직접 쓴 글은 원문 그대로 간다."""
    from app.core import fixtures, policy

    out = dict(policy.DEFAULT_PERSONA_EN)
    for p in policy.PERSONA_PRESETS + policy.HQ_PERSONA_PRESETS:
        if p.get("text_en"):
            out[p["text"]] = p["text_en"]
    for st in fixtures.load().get("stores", {}).values():
        if st.get("persona") and st.get("persona_en"):
            out[st["persona"]] = st["persona_en"]
    return out


def english(value):
    """값 하나를 영어로 — 문자열은 패턴·단어 치환, 목록은 원소마다. 숫자는 그대로."""
    if isinstance(value, list):
        return [english(v) for v in value]
    if not isinstance(value, str) or not re.search(r"[가-힣]", value):
        return value
    out = value
    for pat, to in VALUE_PATTERNS:
        out = re.sub(pat, to, out)
    for ko, en in VALUE_WORDS.items():
        out = out.replace(ko, en)
    return out


def enabled() -> bool:
    return bool(config.TYPESAFE_API_KEY)


def state_for(kind: str, facts: dict, policy_values: dict) -> dict:
    situation = QUESTIONS[kind][0]
    personas = _personas()
    policy = {k: v for k, v in policy_values.items()
              if isinstance(v, (int, float, str, bool)) and k != "fast_decision_min_confidence_pct"}
    if isinstance(policy.get("persona"), str):
        policy["persona"] = personas.get(policy["persona"].strip(), policy["persona"])
    out = {KEY_EN.get(k, k): english(v) for k, v in facts.items()}
    for key, name in SERIES_KEYS.items():
        summary = sales_summary(facts.get(key))
        if summary is not None:
            out[name] = summary
    return {"situation": situation, "facts": out, "policy": policy}


def ask(state: dict, instructions: str, criteria: dict, *, timeout: float = 8.0, attempts: int = 2) -> dict:
    """Choice 질문 하나 → {choice, confidence, probabilities, ms, input_tokens}. 실패는 예외로."""
    body = json.dumps({"state": state, "model": config.JEV_MODEL, "questions": {
        "decision": {"type": "choice", "instructions": instructions, "criteria": criteria}}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": f"Bearer {config.TYPESAFE_API_KEY}", "Content-Type": "application/json"})
    for attempt in range(attempts):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.load(r)
            ans = out["answers"]["decision"]
            return {"choice": ans["choice"], "confidence": float(ans["confidence"]),
                    "probabilities": ans.get("probabilities", {}),
                    "ms": round((time.monotonic() - started) * 1000),
                    "input_tokens": out.get("usage", {}).get("input_tokens", 0)}
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 529) and attempt < attempts - 1:
                time.sleep(1.0)
                continue
            raise
    raise RuntimeError("Jev 호출 실패")


def decide(kind: str, facts: dict, policy_values: dict, allowed: set[str]) -> dict:
    """판단 한 건을 Jev에 묻는다. 선택지는 호출부가 허용한 것만 건넨다."""
    situation, crit = QUESTIONS[kind]
    criteria = {o: c for o, c in crit.items() if o in allowed}
    return ask(state_for(kind, facts, policy_values),
               f"{situation} Which decision fits `facts` under `policy`?", criteria)
