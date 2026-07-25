#!/usr/bin/env bash
# Cloud Run 배포 스크립트 (프로젝트 루트에서 실행)
# 사전 준비: gcloud auth login && gcloud config set project $PROJECT_ID
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT를 설정하세요}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"

# 에이전트 (ADK API 서버)
gcloud run deploy commerce-agent \
  --source . \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --allow-unauthenticated \
  --set-secrets "GOOGLE_API_KEY=google-api-key:latest"

# Secret Manager에 API 키 등록 (최초 1회):
#   echo -n "$GOOGLE_API_KEY" | gcloud secrets create google-api-key --data-file=-
