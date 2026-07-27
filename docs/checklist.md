# 제출 당일 최종 점검 (8/3, 마감 23:59)

> 계획은 [wbs.md](wbs.md), 현재 상태는 [HANDOFF.md](HANDOFF.md).
> 이 문서는 **제출 직전에 훑는 용도** — 빠뜨리면 되돌릴 수 없는 것만 담았다.

## 제출물 4종

- [ ] **프로덕트 소개서 (PPT)** — 타깃 · 문제 · **수익모델** · 아키텍처 네 요소가 모두 있는가
- [ ] **GitHub Repo** — public 전환됐는가, README만 보고 재현 가능한가
- [ ] **데모 영상** — **3분 이내**인가, 실제 온체인 결제 전 과정이 담겼는가
- [ ] **라이브 배포 URL** (가산점) — 지금 접속되는가

## 되돌릴 수 없는 것 — 두 번 확인

- [ ] **키 유출** — `backend/.env`, `payments/.env`, 지갑 키가 커밋에 없는가
      `git log --all -S "AIza" --oneline` 과 `git log --all -S "SOLPLY" --oneline` 이 비어 있는가
- [ ] **레포 public 전환** — `gh repo edit poi2507/solply --visibility public --accept-visibility-change-consequences`
- [ ] 영상에 API 키·지갑 키가 화면에 스치지 않았는가

## 심사 기준 대응 확인

- [ ] **혁신성·UX** — "왜 에이전트인가 / 왜 온체인인가"를 한 문장으로 답할 수 있는가
- [ ] **AI 활용도** — Gemini 판단 지점(검수 대조·협상 심사)이 발표에 드러나는가
- [ ] **인프라 연동** — USDC 결제 + x402가 실제로 동작하는가
- [ ] **실제 구동** — **devnet** explorer 링크가 열리는가 (로컬넷은 심사위원이 검증할 수 없다)

> 주최측 경고: **"목업은 심사 대상에서 제외됩니다."**

## 데모 안전장치

- [ ] devnet 지갑 4개에 SOL(수수료) + USDC 잔액이 넉넉한가
- [ ] RPC 불안정 대비 **사전 녹화 백업 영상**이 있는가
- [ ] Gemini 한도에 걸리지 않게 `LLM_PROVIDER` 설정을 확인했는가
      (Vertex 전환됐으면 무료 티어 한도 문제 없음)
