#!/usr/bin/env bash
# Vertex AI 전환 준비 상태를 점검하고, 되면 실제 호출까지 해본다.
# GCP 결제가 풀린 뒤 이걸 통과하면 backend/.env 에 LLM_PROVIDER=vertex 로 바꾸면 된다.
set -uo pipefail
export PATH="$HOME/.local/bin:$HOME/.local/google-cloud-sdk/bin:$PATH"

ok=0
step() { printf "  %s ... " "$1"; }
pass() { echo "✓ $1"; }
fail() { echo "✗ $1"; ok=1; }

step "1) gcloud 로그인"
ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | head -1)
[ -n "$ACCOUNT" ] && pass "$ACCOUNT" || fail "gcloud auth login 필요"

step "2) 애플리케이션 기본 인증(ADC)"
gcloud auth application-default print-access-token >/dev/null 2>&1 \
  && pass "토큰 발급됨" || fail "gcloud auth application-default login 필요"

step "3) 프로젝트"
PROJECT=$(gcloud config get-value project 2>/dev/null)
[ -n "$PROJECT" ] && [ "$PROJECT" != "(unset)" ] && pass "$PROJECT" || fail "gcloud config set project <ID> 필요"

step "4) 결제 계정"
if [ -n "${PROJECT:-}" ] && [ "$PROJECT" != "(unset)" ]; then
  BILLING=$(gcloud billing projects describe "$PROJECT" --format="value(billingEnabled)" 2>/dev/null)
  [ "$BILLING" = "True" ] && pass "활성" || fail "결제 계정 미연결 — 콘솔에서 활성화 필요"
else
  fail "프로젝트 먼저"
fi

step "5) Vertex AI API"
if [ -n "${PROJECT:-}" ] && [ "$PROJECT" != "(unset)" ]; then
  gcloud services list --enabled --project "$PROJECT" 2>/dev/null | grep -q aiplatform \
    && pass "활성" || fail "gcloud services enable aiplatform.googleapis.com --project $PROJECT"
else
  fail "프로젝트 먼저"
fi

if [ "$ok" -ne 0 ]; then
  echo ""
  echo "위 항목을 해결한 뒤 다시 실행하세요."
  exit 1
fi

step "6) 실제 호출"
cd "$(dirname "${BASH_SOURCE[0]}")/../backend" || exit 1
RESULT=$(GOOGLE_CLOUD_PROJECT="$PROJECT" LLM_PROVIDER=vertex uv run python -c "
from app.llm import factory
m = factory.chat_model(factory.model_for('hq'))
print(m.invoke([('human','한 단어로 답해: 준비됐나?')]).content.strip()[:40])
" 2>&1 | tail -1)
case "$RESULT" in
  *Error*|*error*|*Traceback*) fail "$RESULT" ;;
  *) pass "응답: $RESULT" ;;
esac

echo ""
if [ "$ok" -eq 0 ]; then
  cat <<EOF
✅ Vertex 사용 가능. backend/.env 를 이렇게 바꾸세요:

  LLM_PROVIDER=vertex
  GOOGLE_CLOUD_PROJECT=$PROJECT

  무료 티어 분당 한도에서 벗어나고 \$300 크레딧이 적용됩니다.
EOF
fi
