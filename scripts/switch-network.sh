#!/usr/bin/env bash
# 결제 서비스가 볼 네트워크를 바꾼다.
#
#   bash scripts/switch-network.sh devnet     시연·촬영용 (explorer 링크가 살아난다)
#   bash scripts/switch-network.sh localnet   개발용 (무제한 리허설)
#
# 로컬넷 민트는 validator를 새로 띄울 때마다 바뀌므로 setup-localnet.sh가 기록해둔
# 값을 되살린다. devnet 민트는 Circle 공식 주소로 고정이다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/payments/.env"
API_ENV="$ROOT/backend/.env"
STASH="$ROOT/.dev-logs/localnet-mint"
DEVNET_USDC="4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

TARGET="${1:-}"
[ -f "$ENV_FILE" ] || { echo "✗ payments/.env 가 없습니다"; exit 1; }

current=$(grep '^SOLANA_NETWORK=' "$ENV_FILE" | cut -d= -f2)

set_env() {
  local rpc=$1 net=$2 mint=$3 tmp
  tmp=$(mktemp)
  sed -e "s|^SOLANA_RPC_URL=.*|SOLANA_RPC_URL=$rpc|" \
      -e "s|^SOLANA_NETWORK=.*|SOLANA_NETWORK=$net|" \
      -e "s|^USDC_MINT=.*|USDC_MINT=$mint|" "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"

  # 대시보드도 같은 네트워크를 말해야 한다 — 표시가 어긋나면 심사에서 오해를 산다
  if [ -f "$API_ENV" ]; then
    if grep -q '^SOLANA_NETWORK=' "$API_ENV"; then
      tmp=$(mktemp)
      sed -e "s|^SOLANA_NETWORK=.*|SOLANA_NETWORK=$net|" "$API_ENV" > "$tmp" && mv "$tmp" "$API_ENV"
    else
      printf '\n# 대시보드 표시용 (switch-network.sh가 관리)\nSOLANA_NETWORK=%s\n' "$net" >> "$API_ENV"
    fi
  fi
}

case "$TARGET" in
  devnet)
    # 로컬넷으로 돌아올 때 쓸 민트를 남겨둔다
    if [ "$current" = "localnet" ]; then
      mkdir -p "$(dirname "$STASH")"
      grep '^USDC_MINT=' "$ENV_FILE" | cut -d= -f2 > "$STASH"
    fi
    set_env "https://api.devnet.solana.com" "devnet" "$DEVNET_USDC"
    echo "▶ devnet 전환 완료 (Circle 공식 USDC)"
    echo "  ⚠️  이 상태에서 make dev / setup-localnet.sh 를 돌리면 로컬넷으로 되돌아갑니다."
    echo "     결제 서비스만 재시작하세요: make pay"
    ;;
  localnet)
    mint=""
    [ -f "$STASH" ] && mint=$(cat "$STASH")
    if [ -z "$mint" ]; then
      echo "✗ 로컬넷 민트 기록이 없습니다. setup-localnet.sh 를 먼저 실행하세요."
      exit 1
    fi
    set_env "http://127.0.0.1:8899" "localnet" "$mint"
    echo "▶ localnet 전환 완료 (민트 $mint)"
    ;;
  *)
    echo "현재: $current"
    echo "사용법: bash scripts/switch-network.sh {devnet|localnet}"
    exit 1
    ;;
esac

grep -E '^SOLANA_(RPC_URL|NETWORK)=|^USDC_MINT=' "$ENV_FILE" | sed 's/^/  /'
