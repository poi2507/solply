# CLAUDE.md

GCP × Solana AI Agentic 해커톤 (2026, Demo Day 8/21) 프로젝트. 상세 규칙·심사기준·일정은 README.md 참고.

## 구조
- `agent/` — Python 3.11+, Google ADK + Gemini 에이전트. `uv` 사용 (`uv sync`, `uv run adk web`)
- `payments/` — TypeScript(Node), Express + @solana/web3.js. Solana **devnet** USDC 결제 API (`npm run dev`, 포트 3000)
- `infra/` — Cloud Run 배포 (Dockerfile.agent, deploy.sh)
- `scripts/setup-solana.sh` — devnet 지갑 생성·에어드랍

## 원칙
- 결제는 devnet 전용. 메인넷 전환 금지.
- 키페어·API 키는 절대 커밋하지 않는다 (.env, ~/.config/solana/hackathon.json)
- 에이전트의 자율 결제는 `AGENT_SPEND_LIMIT_USDC` 한도 내에서만 — 이 한도 로직은 심사 포인트(자율 결제 + 정책 한도)이므로 유지
- 심사에서 "실제 트랜잭션 실행 로그"를 확인하므로 결제 성공 시 signature와 explorer 링크를 반드시 로그로 남긴다
