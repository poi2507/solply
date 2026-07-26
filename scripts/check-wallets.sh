#!/usr/bin/env bash
# Solply 에이전트 지갑 4개의 devnet SOL/USDC 잔액 확인
set -uo pipefail
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"

USDC_MINT="4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

printf "%-9s %-45s %10s %10s\n" "WALLET" "ADDRESS" "SOL" "USDC"
for n in hq store-a store-b store-c; do
  ADDR=$(solana-keygen pubkey "$HOME/.config/solana/solply/$n.json")
  SOL=$(solana balance "$ADDR" --url devnet 2>/dev/null | awk '{print $1}')
  USDC=$(solana balance "$ADDR" --url devnet --output json 2>/dev/null >/dev/null; \
         spl-token accounts --owner "$ADDR" --url devnet 2>/dev/null | grep "$USDC_MINT" | awk '{print $2}')
  printf "%-9s %-45s %10s %10s\n" "$n" "$ADDR" "${SOL:-0}" "${USDC:-0}"
done

echo ""
echo "SOL 받기 : https://faucet.solana.com  (주소 붙여넣기, 지갑 4개 모두)"
echo "USDC 받기: https://faucet.circle.com  (Solana Devnet 선택, 가맹점 3곳)"
