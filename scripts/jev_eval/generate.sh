#!/usr/bin/env bash
# 평가셋 생성 — 실제 에이전트 코드 + Vertex 판단, 결제는 가짜 서비스. devnet은 건드리지 않는다.
# 사용: scripts/jev_eval/generate.sh [틱 수]   → backend/.jev-eval/state.json 의 decision_log
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TICKS="${1:-12}"
OUT="$ROOT/backend/.jev-eval"; mkdir -p "$OUT"
cd "$ROOT/backend"
uv run uvicorn --app-dir "$ROOT/scripts/jev_eval" fake_payments:app --port 3911 --log-level warning &
FAKE=$!
export SOLPLY_STORE=local SOLPLY_STATE_PATH="$OUT/state.json" LLM_PROVIDER=vertex \
       PAYMENTS_API_URL=http://127.0.0.1:3911 SOLPLY_API_URL=http://127.0.0.1:8911 \
       SOLANA_NETWORK=localnet PAYSH_ENABLED=0 TICK_ENABLED=1 SIM_DEMAND_ENABLED=1 \
       SHOP_TRIGGER_ENABLED=0 SOLPLY_ADMIN_TOKEN= DECISION_LOG=1
uv run uvicorn app.main:app --port 8911 --log-level warning &
API=$!
trap 'kill $FAKE $API 2>/dev/null || true' EXIT
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8911/api/health >/dev/null && break; sleep 1; done
for i in $(seq 1 "$TICKS"); do
  t0=$(date +%s)
  curl -s -X POST http://127.0.0.1:8911/api/ticks/run -o /dev/null -w "tick $i: %{http_code}" || true
  n=$(python3 -c "import json;print(len(json.load(open('$OUT/state.json')).get('decision_log',{})))" 2>/dev/null || echo 0)
  echo "  ($(( $(date +%s) - t0 ))s, decisions so far: $n)"
done
