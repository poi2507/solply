"""빠른 판단 — TypeSafe Jev (System One 결정 모델).

LLM이 문장을 생성해 결론을 뽑는 대신, 선택지마다 확률을 매겨 하나를 고른다.
확신도(confidence)가 함께 오므로 "이 판단을 기계에 맡겨도 되는가"를 숫자로 가를 수 있다.

라이브에 넘긴 범위는 평가(scripts/jev_eval, 69건 Vertex 대비 96% 일치 — 확신도 0.5 이상은
전부 일치)로 확인한 판단 종류뿐이다. 나머지는 여기로 오지 않는다.
금액·수량은 여전히 코드가 계산한다 — Jev가 고르는 것은 선택지 하나뿐이다.
"""

import json
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
              {"accept": "Sales have risen over several days, so the larger order matches real demand",
               "counter": "Sales are flat or a one-day spike, so trim to the base quantity",
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
                     {"accept": "HQ's reading of flat demand is right, so take the smaller quantity",
                      "insist": "The store's own sales show real demand, so keep the original quantity"}),
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
# 발주 축소 응답(order_adjust)은 11건 중 3건 불일치라 뺐고(9/30 재생에서도 확신도 높게
# 반대로 답함), 표본이 없던 종류(차감·유예·역제안 응답·직거래 가격)도 LLM이 계속 판단한다.
LIVE_KINDS = {"supply_route", "p2p_trade", "order", "brokerage"}

# Jev가 골라도 LLM으로 넘기는 선택 — 중개 수락은 "어느 후보"까지 골라야 하는데
# Jev 질문은 수락/거절만 묻는다. 거절(이번엔 중개 안 함)만 바로 확정한다.
NEEDS_SYSTEM_TWO = {("brokerage", "accept")}


def enabled() -> bool:
    return bool(config.TYPESAFE_API_KEY)


def state_for(kind: str, facts: dict, policy_values: dict) -> dict:
    situation = QUESTIONS[kind][0]
    return {
        "situation": situation,
        "facts": {KEY_EN.get(k, k): v for k, v in facts.items()},
        "policy": {k: v for k, v in policy_values.items()
                   if isinstance(v, (int, float, str, bool)) and k != "fast_decision_min_confidence_pct"},
    }


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
