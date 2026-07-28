.DEFAULT_GOAL := help
SHELL := /bin/bash
PATH := $(HOME)/.local/bin:$(HOME)/.local/node/bin:$(HOME)/.local/share/solana/install/active_release/bin:$(PATH)

.PHONY: help setup dev chain api pay demo demo-mock test lint clean

help:              ## 사용 가능한 명령
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:             ## 백엔드·결제 서비스 의존성 설치
	cd backend && uv sync
	cd payments && npm install

db:                ## PostgreSQL 초기화·기동 (:5432)
	bash scripts/setup-postgres.sh

db-stop:           ## PostgreSQL 중지
	PATH=$$HOME/.local/pg-env/bin:$$PATH pg_ctl -D $$HOME/.local/pgdata stop

psql:              ## DB 접속
	PATH=$$HOME/.local/pg-env/bin:$$PATH psql solply

dev:               ## 전체 스택 기동 (블록체인 + 결제 + API/대시보드)
	bash scripts/dev.sh

chain:             ## 로컬 블록체인만 기동
	solana-test-validator --reset --gossip-port 8010 --limit-ledger-size 50000000 \
		--clone MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr \
		--url https://api.mainnet-beta.solana.com

pay:               ## 결제 서비스만 (:3000)
	cd payments && npm run dev

api:               ## API + 대시보드만 (:8080)
	cd backend && uv run uvicorn app.main:app --reload --port 8080

demo:              ## 데모 3종 — Gemini 판단 (심사용, 느림)
	cd backend && uv run python demo.py

demo-mock:         ## 데모 3종 — 규칙 기반 (리허설용, 빠름 / 온체인 결제는 동일)
	cd backend && LLM_PROVIDER=mock uv run python demo.py

vertex-check:      ## Vertex AI 전환 준비 상태 점검 (GCP 결제 해결 후)
	bash scripts/vertex-check.sh

test:              ## 백엔드 테스트 (임시 JSON 저장소로 격리 — 라이브 DB를 더럽히지 않는다)
	cd backend && SOLPLY_STORE=local SOLPLY_STATE_PATH=/tmp/solply-test-state.json uv run pytest -q
	rm -f /tmp/solply-test-state.json

lint:              ## 포맷·린트
	cd backend && uv run ruff check app demo.py
	cd payments && npx tsc --noEmit

clean:             ## 로컬 상태·로그 정리 (JSON 저장소 + DB 비우기)
	rm -f backend/data/state.json
	rm -rf .dev-logs   # validator ledger 포함
	-cd backend && uv run python -c "from app.db import store; store.reset()" 
