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

from app.llm import jev  # noqa: E402 — 질문·경계 조건은 라이브와 같은 정의를 쓴다

MODEL = config.JEV_MODEL
KEY_EN = jev.KEY_EN
QUESTIONS = jev.QUESTIONS


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
