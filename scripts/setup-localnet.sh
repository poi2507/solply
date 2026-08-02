#!/usr/bin/env bash
# Solply 로컬넷 개발 환경 셋업.
# 주최측 권장(솔라나 세션 p17): 개발은 Localnet에서 무제한 반복, Devnet은 시연 직전에만.
#
# 사용법: validator가 떠 있는 상태에서 bash scripts/setup-localnet.sh
# (make dev가 새 validator를 띄울 때 자동 실행한다. 지갑·payments/.env가 없으면 만든다.)
set -euo pipefail
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"

RPC="http://127.0.0.1:8899"
DIR="${SOLPLY_WALLET_DIR:-$HOME/.config/solana/solply}"
HQ_KEY="$DIR/hq.json"

echo "▶ validator 연결 확인"
solana cluster-version --url "$RPC" >/dev/null

echo "▶ 지갑 4개 확인 — 없으면 생성"
mkdir -p "$DIR"
for n in hq store-a store-b store-c; do
  if [ ! -f "$DIR/$n.json" ]; then
    solana-keygen new --no-bip39-passphrase --silent --outfile "$DIR/$n.json" >/dev/null
    echo "  + $n.json 생성"
  fi
done

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

# 민트는 validator를 새로 띄울 때마다 바뀐다. 손으로 옮기게 두면 반드시 잊고,
# 결제 서비스가 없는 민트를 붙들어 500을 낸다. 그래서 여기서 직접 갱신한다.
ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/payments/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "${ENV_FILE}.example" "$ENV_FILE"
  echo "▶ payments/.env 생성 (.env.example 복사)"
fi
set_env() {  # set_env KEY VALUE — 있으면 교체, 없으면 추가
  if grep -q "^$1=" "$ENV_FILE"; then
    tmp=$(mktemp); sed "s|^$1=.*|$1=$2|" "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"
  else
    echo "$1=$2" >> "$ENV_FILE"
  fi
}
set_env SOLANA_RPC_URL "$RPC"
set_env SOLANA_NETWORK localnet
set_env USDC_MINT "$MINT"
echo "▶ payments/.env 갱신 (USDC_MINT=$MINT)"

cat <<EOF

✅ 로컬넷 준비 완료 — payments/.env 는 자동 갱신됐습니다.

  SOLANA_RPC_URL=$RPC
  SOLANA_NETWORK=localnet
  USDC_MINT=$MINT

EOF
