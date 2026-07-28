#!/usr/bin/env bash
# devnet SOL 분배 — 운영진에게 hq 지갑으로 한 번에 받은 뒤 지점 지갑에 나눈다.
#
# 주소 4개를 각각 요청하는 것보다 hq 하나로 받는 편이 확실하고, 운영진 손도 덜 간다.
# 사용법: bash scripts/fund-devnet.sh [지점당_SOL]   (기본 1.5)
set -euo pipefail
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"

PER=${1:-1.5}
DIR="$HOME/.config/solana/solply"
RPC="https://api.devnet.solana.com"
HQ_KEY="$DIR/hq.json"
HQ=$(solana-keygen pubkey "$HQ_KEY")

echo "▶ devnet 잔액 확인"
BAL=$(solana balance "$HQ" --url "$RPC" | awk '{print $1}')
echo "  hq: $BAL SOL"

NEED=$(python3 -c "print(round($PER * 3 + 0.1, 2))")
if python3 -c "import sys; sys.exit(0 if float('$BAL') < float('$NEED') else 1)"; then
  cat <<EOF

✗ 잔액이 부족합니다 (필요 ${NEED} SOL 이상).
  운영진에게 아래 주소로 SOL을 요청하세요:

    $HQ

  받은 뒤 이 스크립트를 다시 실행하면 지점 지갑에 나눠줍니다.
EOF
  exit 1
fi

for name in store-a store-b store-c; do
  ADDR=$(solana-keygen pubkey "$DIR/$name.json")
  BEFORE=$(solana balance "$ADDR" --url "$RPC" | awk '{print $1}')
  solana transfer "$ADDR" "$PER" --url "$RPC" --keypair "$HQ_KEY" \
    --allow-unfunded-recipient --no-wait >/dev/null
  echo "  $name ← $PER SOL (기존 $BEFORE)"
done

# USDC 토큰 계정(ATA)을 미리 만들어 둔다.
# 첫 전송 때 만들면 devnet에서 수 초가 더 걸려 데모가 타임아웃될 수 있다 —
# 촬영 도중 겪을 일이 아니므로 준비 단계에서 해치운다.
echo ""
echo "▶ USDC 토큰 계정 준비"
USDC="4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
for name in hq store-a store-b store-c; do
  ADDR=$(solana-keygen pubkey "$DIR/$name.json")
  if spl-token accounts --owner "$ADDR" --url "$RPC" 2>/dev/null | grep -q "$USDC"; then
    echo "  $name 이미 있음"
  else
    spl-token create-account "$USDC" --owner "$ADDR" --url "$RPC" \
      --fee-payer "$HQ_KEY" >/dev/null 2>&1 && echo "  $name 생성" || echo "  $name 생성 실패"
  fi
done

sleep 8
echo ""
echo "▶ 최종 잔액"
for name in hq store-a store-b store-c; do
  ADDR=$(solana-keygen pubkey "$DIR/$name.json")
  printf "  %-8s %s SOL\n" "$name" "$(solana balance "$ADDR" --url "$RPC" | awk '{print $1}')"
done
echo ""
echo "USDC는 별도입니다 → https://faucet.circle.com (Solana Devnet)"
echo "  store-a·store-b 만 받으세요. store-c는 잔액 부족이 유예 시나리오의 전제입니다."
