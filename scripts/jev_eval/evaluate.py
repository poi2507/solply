"""Jev vs 현재 판단(Vertex) — 같은 입력을 Jev에 다시 넣어 결정 일치율·지연·확신도를 잰다.

사용 (backend/에서):
  SOLPLY_STORE=local SOLPLY_STATE_PATH=.jev-eval/state.json \\
    uv run python ../scripts/jev_eval/evaluate.py [--limit N]
입력: decision_log (judge.py가 판단마다 남긴 facts·정책·결정)
출력: .jev-eval/results.json + 콘솔 요약

Jev는 영어가 1순위라 사실 키를 영어로 옮기고, 결정 선택지마다 경계 조건을 적는다
(TypeSafe 문서의 "literal reading" 주의). 금액·수량 비교는 모델이 아니라 원래 코드가 한다 —
여기서 보는 건 "같은 상황에서 같은 선택을 하는가"다.
"""

import argparse
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import config  # noqa: E402
from app.core import policy as policy_mod  # noqa: E402
from app.db import store  # noqa: E402

MODEL = "jev-1.13.0"  # 임계값을 맞출 버전을 고정한다 (별칭은 옮겨간다)

KEY_EN = {
    "품목": "item",
    "지점_일별판매_7일(과거→오늘)": "store_daily_sales_7d_oldest_to_today",
    "전국_일별판매_7일(해당 지점 제외)": "national_daily_sales_7d_excluding_this_store",
    "본사_창고_잔량": "hq_warehouse_stock",
    "후보 목록": "candidates",
}

# 판단 종류별: 무엇을 묻는가 + 선택지별 경계 조건 (judge.py의 지시와 같은 뜻)
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
    "brokerage": ("HQ decides whether to broker one stock transfer between stores from the candidate list.",
                  {"accept": "One candidate is clearly worth brokering: the short store is urgent and the surplus store can spare it",
                   "reject": "No candidate is clearly worth brokering this round",
                   "counter": "Not applicable"}),
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


def _key() -> str:
    if config.TYPESAFE_API_KEY:
        return config.TYPESAFE_API_KEY
    sys.exit("TYPESAFE_API_KEY is empty — put it in backend/.env")


def ask(state: dict, instructions: str, criteria: dict, key: str) -> tuple[dict, float, int]:
    body = json.dumps({"state": state, "model": MODEL, "questions": {
        "decision": {"type": "choice", "instructions": instructions, "criteria": criteria}}}).encode()
    req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(4):
        t = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r)
            return out["answers"]["decision"], (time.monotonic() - t) * 1000, out["usage"]["input_tokens"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    key = _key()
    logs = [d for d in store.list_docs("decision_log") if d.get("kind") in QUESTIONS]
    logs.sort(key=lambda d: d.get("at", ""))
    logs = logs[: args.limit]
    hq_policy = policy_mod.get("hq").as_prompt_values()
    rows = []
    for d in logs:
        situation, crit = QUESTIONS[d["kind"]]
        allowed = [o.strip() for o in d.get("options", "").split("/") if o.strip()]
        criteria = {o: crit[o] for o in allowed if o in crit and crit[o] != "Not applicable"}
        facts = {KEY_EN.get(k, k): v for k, v in (d.get("facts") or {}).items()}
        pol = d.get("policy") or (hq_policy if d["agent"] == "hq" else {})
        state = {"situation": situation, "facts": facts, "policy": pol}
        ans, ms, tokens = ask(state, f"{situation} Which decision fits `facts` under `policy`?", criteria, key)
        rows.append({"id": d.get("id"), "agent": d["agent"], "kind": d["kind"],
                     "baseline": d.get("decision"), "baseline_ms": d.get("latency_ms"),
                     "baseline_provider": d.get("provider"),
                     "jev": ans["choice"], "confidence": ans["confidence"],
                     "probabilities": ans["probabilities"], "jev_ms": round(ms), "tokens": tokens})
        print(f"{d['kind']:<17} base={d.get('decision'):<8} jev={ans['choice']:<8} "
              f"conf={ans['confidence']:.2f} {ms:4.0f}ms vs {d.get('latency_ms')}ms")

    if not rows:
        print("no decisions in decision_log")
        return
    out = Path(config.STATE_PATH).parent / "results.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    agree = [r for r in rows if r["jev"] == r["baseline"]]
    print(f"\n{len(rows)} decisions · agreement {len(agree)}/{len(rows)} = {len(agree)/len(rows):.0%}")
    by_kind = {}
    for r in rows:
        k = by_kind.setdefault(r["kind"], [0, 0])
        k[0] += r["jev"] == r["baseline"]; k[1] += 1
    for k, (a, n) in sorted(by_kind.items()):
        print(f"  {k:<17} {a}/{n}")
    hi = [r for r in rows if r["confidence"] >= 0.8]
    lo = [r for r in rows if r["confidence"] < 0.8]
    for name, part in (("confidence ≥ 0.8", hi), ("confidence < 0.8", lo)):
        if part:
            a = sum(r["jev"] == r["baseline"] for r in part)
            print(f"  {name}: {len(part)} decisions, agreement {a/len(part):.0%}")
    print(f"  latency  jev median {statistics.median(r['jev_ms'] for r in rows):.0f}ms · "
          f"baseline median {statistics.median(r['baseline_ms'] or 0 for r in rows):.0f}ms")
    print(f"  cost     {sum(r['tokens'] for r in rows)} input tokens ≈ "
          f"${sum(r['tokens'] for r in rows) * 0.042 / 1e6:.4f}")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
