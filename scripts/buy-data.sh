#!/usr/bin/env bash
# 데이터 상점 구매 시연 — 402 견적 → USDC 지불 → 증빙 제출 → 지수 수령
#
# 사용: ./scripts/buy-data.sh [market|demand] [SKU] [구매자지갑]
#   예: ./scripts/buy-data.sh market CHK-10 trader
#
# 구매자 기본값은 trader — 데이터 상점의 외부 거래처 지갑(프랜차이즈 풀 밖).
# 서버는 서명을 조회 키로만 쓰므로 누가 냈는지는 체인이 증명한다 —
# 어떤 외부 지갑이든 USDC를 보내고 서명만 제출하면 지수를 받는다.
set -euo pipefail

API=${API:-https://solply-api-965647250280.us-central1.run.app}
PRODUCT=${1:-market}
SKU=${2:-CHK-10}
BUYER=${3:-trader}

echo "① 견적 요청 (402 기대) — $PRODUCT/$SKU"
QUOTE=$(curl -s "$API/x402/data/$PRODUCT/$SKU")
ORDER=$(echo "$QUOTE" | python3 -c "import json,sys; print(json.load(sys.stdin)['extensions']['solply.dataOrder']['id'])")
PAYTO=$(echo "$QUOTE" | python3 -c "import json,sys; print(json.load(sys.stdin)['accepts'][0]['payTo'])")
AMOUNT=$(echo "$QUOTE" | python3 -c "import json,sys; print(int(json.load(sys.stdin)['accepts'][0]['amount'])/1e6)")
echo "   주문 $ORDER — $AMOUNT USDC → $PAYTO"

echo "② USDC 지불 (memo = 주문 ID)"
PAYURL=$(gcloud run services describe solply-payments --region us-central1 --format 'value(status.url)')
SIG=$(curl -s -X POST "$PAYURL/pay" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d "{\"from\":\"$BUYER\",\"recipient\":\"$PAYTO\",\"amount\":$AMOUNT,\"memo\":\"$ORDER\"}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['signature'])")
echo "   tx $SIG"

echo "③ 증빙 제출 → 지수 수령"
HEADER=$(python3 -c "import base64,json; print(base64.b64encode(json.dumps({'x402Version':2,'payload':{'signature':'$SIG'}}).encode()).decode())")
curl -s -X POST "$API/x402/data/orders/$ORDER/settle" -H "PAYMENT-SIGNATURE: $HEADER" | python3 -m json.tool
