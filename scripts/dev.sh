#!/usr/bin/env bash
# Solply 로컬 개발 스택을 한 번에 띄운다.
#
#   solana-test-validator  :8899   로컬 블록체인
#   payments (Express)     :3000   USDC 전송·검증
#   api (FastAPI)          :8080   대시보드 + x402 + 프론트
#
# 종료: Ctrl+C
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/.dev-logs"
mkdir -p "$LOG"
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$HOME/.local/share/solana/install/active_release/bin:$PATH"

cleanup() {
  echo ""
  echo "▶ 종료 중..."
  [[ -n "${PAY_PID:-}" ]] && kill "$PAY_PID" 2>/dev/null
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null
  [[ -n "${VAL_PID:-}" ]] && kill "$VAL_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

MEMO=MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr

if solana cluster-version --url localhost >/dev/null 2>&1; then
  echo "✓ validator 이미 실행 중"
else
  echo "▶ validator 기동 (memo 프로그램 복제)"
  # gossip 기본 포트 8000이 Docker 등과 충돌할 수 있어 8010으로 고정
  solana-test-validator --reset --quiet --ledger "$LOG/ledger" --gossip-port 8010 \
    --clone "$MEMO" --url https://api.mainnet-beta.solana.com > "$LOG/validator.log" 2>&1 &
  VAL_PID=$!
  for _ in $(seq 1 40); do
    solana cluster-version --url localhost >/dev/null 2>&1 && break
    sleep 1
  done
  echo "✓ validator 준비"
  bash "$ROOT/scripts/setup-localnet.sh" | tail -6
fi

echo "▶ payments (:3000)"
(cd "$ROOT/payments" && npm run dev > "$LOG/payments.log" 2>&1) &
PAY_PID=$!

echo "▶ api + 대시보드 (:8080)"
(cd "$ROOT/backend" && uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 > "$LOG/api.log" 2>&1) &
API_PID=$!

sleep 6
echo ""
echo "──────────────────────────────────────────"
echo "  대시보드  http://localhost:8080"
echo "  로그      $LOG/"
echo ""
echo "  데모 실행: make demo       (Gemini)"
echo "           make demo-mock  (규칙 기반, 빠름)"
echo "──────────────────────────────────────────"
wait
