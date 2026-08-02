# Solply — Settle On Ledger, for supply

**프랜차이즈 본사와 가맹점 사이의 식자재 대금(물대)을, AI 에이전트들이 청구·검수·협상·온체인 정산까지 사람 개입 없이 처리합니다.**

에이전트는 청구서를 받으면 입고 기록과 대조하고, 수량이 틀리면 차액을 깎아달라 협상하고,
발주한 적 없는 품목이면 거부하고, 점주가 정한 한도를 넘으면 멈춰서 사람을 부릅니다.
합의가 되면 x402 프로토콜로 Solana 위에서 USDC를 지불하고, 본사가 온체인에서 대조해 정산을 확정합니다.

| | |
|---|---|
| 🟢 **지금 돌고 있는 화면** | **https://solply-api-965647250280.us-central1.run.app** |
| 🛒 손님으로 참여해보기 | [/shop](https://solply-api-965647250280.us-central1.run.app/shop) — 구매 한 번이 에이전트 조달을 일으킵니다 |
| 🎬 데모 영상 (2분 55초) | 제출물에 함께 첨부했습니다 · 장면별 대본은 [video-script.md](docs/video-script.md) |
| 📖 코드 레벨 해부도 | [deep-dive.html](docs/deep-dive.html) — 8부 26장, 브라우저로 열면 됩니다 |

---

## 이건 목업이 아닙니다

주최측이 "목업은 심사 대상에서 제외"라고 명시했으므로, 무엇이 실제인지 먼저 밝힙니다.

**실제로 일어나는 일** — 위 라이브 URL은 **2026-07-29부터 사람 없이 10분마다 스스로 거래**하고 있습니다
(Cloud Scheduler → 판매 → 카드정산 → 조달 → 재입고 → 예약납부). 모든 결제는 **Solana devnet의 실제 트랜잭션**이고,
공개 익스플로러에서 누구나 검증할 수 있습니다. 예를 들어 이 청구서:

```
INV-0731-C76 · 1.5 USDC
https://explorer.solana.com/tx/3fs9sHQa6XtZLm9fGWUXYMyRJyyFxAmFKSvPW5cFNjHGuyjCux6APYE9P6oPuPTjemajZNGrQrrQKtaupJqdvMDz?cluster=devnet
```

**정직하게 밝히는 한계** — devnet 토큰은 실제 가치가 없습니다(테스트 네트워크). 시세 데이터를 사는
pay.sh는 `--sandbox` 모드라 그 결제는 공개 체인에 남지 않고, **시세 숫자 자체는 주최측 데모 API가 만들어 주는 값**입니다
(화면에도 `제공 pay.sh 데모 시세`로 표기). 메인넷은 사고 방지를 위해 코드 규칙으로 금지했습니다.
그 외 정산·직거래·카드정산은 전부 devnet 실거래입니다.

## 3분 안에 확인하는 방법

1. **[라이브 대시보드](https://solply-api-965647250280.us-central1.run.app)** 접속 → 역할 선택에서 **시스템 관리자**
2. **실행 로그** 패널 — 에이전트들이 방금 한 일이 시간순으로 쌓여 있습니다.
   `x402 정산 완료` 옆의 서명을 누르면 익스플로러로 넘어갑니다
3. **청구서** 표에서 아무 행이나 누르면 그 한 건의 **발행 → 검수 → 협상 → 결제 → 정산** 전 과정이 펼쳐집니다.
   금액이 `7.00 → 6.50`처럼 바뀐 행이 있으면 그게 **에이전트가 깎아낸 것**입니다
4. 마스트헤드의 `‹ 오늘 ›`로 **지난 날짜**를 넘겨보면 그날의 거래만 보입니다
5. **[/shop](https://solply-api-965647250280.us-central1.run.app/shop)** 에서 아무거나 하나 사보세요 —
   재고가 안전선을 깨면 다음 틱(10분 내)에 에이전트가 조달을 시작합니다

## 심사 기준별로 어디를 보면 되는가

| 기준 | 우리가 한 것 | 코드 |
|---|---|---|
| **① 혁신성·UX** | 에이전트가 **따지고·거부하고·멈춘다**. 협상 6종(정상·차감·유예·분할 역제안·거부·지점 간 직거래). 손님이 직접 수요를 만드는 `/shop` | `agents/*/graph.py` · `api/shop.py` |
| **② AI 활용도** | **Vertex AI(Gemini)** + **LangGraph**(거래 두뇌 — 경로가 그래프로 드러난다) + **ADK**(사람 창구 — 대화로 승인). 분담에 근거가 있다 | `llm/judge.py` · `agents/` · `assistant/` |
| **③ 인프라 연동** | **USDC**(정산 통화) · **x402**(우리가 판매자·구매자 양쪽을 직접 구현) · **pay.sh**(에이전트가 판단 재료를 사는 레일) — 셋이 각각 다른 역할로 실사용 | `core/protocol.py` · `api/x402.py` · `core/market.py` |
| **④ 실제 구동** | 라이브가 **10분마다 스스로** 거래 중 — 청구서 472건·직거래 489건, 그중 사람이 개입한 결정은 9건. 모든 결제에 devnet 익스플로러 링크 | `core/economy.py` · `api/dashboard.py` |

세부 주제 대응: **A**(결제 요청 생성→입금→정산) = 402 발행·온체인 3중 대조 ·
**B**(정책 한도 내 자율 서명) = `route_after_cashflow`의 상한·하한·승인 경계 ·
**C**(A2A 협상) = 두 에이전트 그래프의 왕복.

## 직접 돌려보기

필요한 도구: **uv** · **Node 20+** · **Docker**(PostgreSQL용) · **Solana CLI**(`solana-test-validator`).
체인 없이 로직만 확인하려면 `make setup` 후 `make test`만으로 충분합니다 (137개, 3초).

```bash
make setup     # 의존성 (backend: uv · payments: npm)
make db        # PostgreSQL 기동 (:5432)
make dev       # 블록체인 + 결제 서비스 + API/대시보드 → http://localhost:8080

# 다른 터미널에서 — 협상 6종을 처음부터 끝까지
make demo-mock # 규칙 기반 판단(빠름). 온체인 결제는 실제로 발생합니다
make demo      # Gemini 판단 (Vertex 설정 필요)

make tick      # 경제 루프 한 바퀴 (판매→카드정산→조달→재입고→예약납부)
make test      # 137개
make help      # 전체 명령
```

**개발은 로컬넷, 시연은 devnet.** `make localnet` / `make devnet`으로 전환합니다.
환경 변수는 `backend/.env.example` · `payments/.env.example` 참고
(핵심은 `LLM_PROVIDER`(gemini|vertex|mock) · `SOLPLY_STORE`(local|postgres) · `SOLANA_NETWORK`).
**`LLM_PROVIDER=mock`이면 LLM 없이도 6종이 완주합니다** — 판단 규칙이 `llm/rules.py`에 따로 있어서,
API 키 없이도 온체인 결제까지 그대로 검증할 수 있습니다.

## 구조

```
backend/app/
├── agents/            에이전트 — hq/ · store/ 각각 graph(배선)·node(단계)·state(기억)·tools(부수효과)
│                      + prompts/{role,task,policy,output}.md   ← 개인별 수치는 프롬프트에 쓰지 않는다
├── core/              규칙과 계산 — protocol(x402) · economy(경제 틱) · policy · credit
│                      market(pay.sh 시세 구매) · status·events(상태·라벨 단일 출처) · kst
├── api/               8개 라우터 — x402 · dashboard(+SSE) · approvals · schedules · policy · shop · ticks · assistant
├── llm/               factory(gemini|vertex|mock) · judge(판단 호출 지점) · rules(LLM 없는 규칙)
├── db/                store 파사드 → local_store(JSON) / postgres_store(JSONB 2테이블)
└── assistant/         ADK 어시스턴트 — 사람 권한(승인·반려·예약)만 도구로 갖는다
payments/              TypeScript — 지갑 열쇠를 든 유일한 곳 (Cloud Run에서 비공개로 잠근다)
frontend/              빌드 없는 정적 대시보드 + 손님 페이지
scripts/video/         Playwright + ffmpeg 촬영기 — 코드가 바뀌면 영상을 다시 만든다
```

설계 의도와 코드 레벨 설명은 **[deep-dive.html](docs/deep-dive.html)** (8부 26장)에 있습니다 —
왜 프레임워크를 둘 쓰는지, 왜 재고를 저장하지 않는지, 어떤 버그를 어떻게 잡았는지까지.

## 더 읽을 것

[제품 설계](docs/product-design.md) · [수익 모델](docs/revenue-model.md) · [의사결정 로그](docs/decision-log.md) ·
[클라우드·pay.sh 구축 기록](docs/cloud-paysh-report.html) · [영상 대본](docs/video-script.md) ·
[해커톤 맥락](docs/hackathon-context.md) · [인수인계](docs/HANDOFF.md) · [작업 계획](docs/wbs.md)
