#!/usr/bin/env bash
# Solply 로컬넷 개발 환경 셋업.
# 주최측 권장(솔라나 세션 p17): 개발은 Localnet에서 무제한 반복, Devnet은 시연 직전에만.
#
# 사용법:
#   1) 터미널 A: solana-test-validator --reset
#   2) 터미널 B: bash scripts/setup-localnet.sh
#   3) 출력된 USDC_MINT를 payments/.env 에 반영
set -euo pipefail
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"

RPC="http://127.0.0.1:8899"
DIR="$HOME/.config/solana/solply"
HQ_KEY="$DIR/hq.json"

echo "▶ validator 연결 확인"
solana cluster-version --url "$RPC" >/dev/null

echo "▶ 지갑 4개에 SOL 에어드랍"
for n in hq store-a store-b store-c; do
  solana airdrop 10 "$(solana-keygen pubkey "$DIR/$n.json")" --url "$RPC" >/dev/null
done

echo "▶ 로컬 USDC 민트 생성 (decimals 6, mint authority = hq)"
MINT=$(spl-token create-token --decimals 6 --url "$RPC" --fee-payer "$HQ_KEY" --mint-authority "$HQ_KEY" \
  | awk '/Address:/ {print $2}')
echo "  USDC_MINT=$MINT"

echo "▶ 가맹점 토큰 계정 생성 및 USDC 지급"
# 데모 시나리오: A·B는 결제 여력 충분, C는 잔액 부족 → 유예 협상 트리거
declare -a AMOUNTS=("store-a:100" "store-b:100" "store-c:5")
for entry in "${AMOUNTS[@]}"; do
  name="${entry%%:*}"; amt="${entry##*:}"
  addr=$(solana-keygen pubkey "$DIR/$name.json")
  spl-token create-account "$MINT" --owner "$addr" --url "$RPC" --fee-payer "$HQ_KEY" >/dev/null 2>&1 || true
  spl-token mint "$MINT" "$amt" --recipient-owner "$addr" --url "$RPC" \
    --fee-payer "$HQ_KEY" --mint-authority "$HQ_KEY" >/dev/null
  echo "  $name: $amt USDC"
done
# HQ도 수취용 토큰 계정을 미리 만들어 둔다
spl-token create-account "$MINT" --owner "$(solana-keygen pubkey "$HQ_KEY")" --url "$RPC" --fee-payer "$HQ_KEY" >/dev/null 2>&1 || true

cat <<EOF

✅ 로컬넷 준비 완료. payments/.env 를 아래로 설정하세요:

  SOLANA_RPC_URL=$RPC
  SOLANA_NETWORK=localnet
  USDC_MINT=$MINT

EOF
