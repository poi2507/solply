# Solply — Settle On Ledger, for supply

**프랜차이즈 본사와 가맹점 사이의 식자재 대금(물대)을, AI 에이전트들이 청구·검수·협상·온체인 정산까지 사람 개입 없이 처리합니다.**

에이전트는 청구서를 받으면 입고 기록과 대조하고, 수량이 틀리면 차액을 깎아달라 협상하고,
발주한 적 없는 품목이면 거부하고, 점주가 정한 한도를 넘으면 멈춰서 사람을 부릅니다.
합의가 되면 x402 프로토콜로 Solana 위에서 USDC를 지불하고, 본사가 온체인에서 대조해 정산을 확정합니다.

| | |
|---|---|
| 🟢 **지금 돌고 있는 화면** | **https://solply-api-965647250280.us-central1.run.app** |
| 🛒 손님으로 참여해보기 | [/shop](https://solply-api-965647250280.us-central1.run.app/shop) — 구매 한 번이 에이전트 조달을 일으킵니다 |
| 🎬 데모 영상 (2분 55초) | **https://youtu.be/Tx40wJV4UVQ** · 장면별 대본은 [video-script.md](docs/video-script.md) |

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
| **③ 인프라 연동** | **USDC**(정산 통화 — Circle 공식 devnet 민트) · **x402**(판매자·구매자 양쪽을 직접 구현 — 에이전트가 자기 지갑으로 판단 재료를 사고, 우리 체결 지수를 같은 규약으로 판다) · **pay.sh**(첫 시세 출처였고 지금은 폴백 — 카탈로그 입점은 메인넷 로드맵) | `core/protocol.py` · `api/x402.py` · `core/market.py` · `api/data_products.py` |
| **④ 실제 구동** | 라이브가 **10분마다 스스로** 거래 중 — 청구서 1,661건·직거래 1,526건, 그중 사람이 개입한 결정은 9건. 모든 결제에 devnet 익스플로러 링크 | `core/economy.py` · `api/dashboard.py` |

세부 주제 대응: **A**(결제 요청 생성→입금→정산) = 402 발행·온체인 3중 대조 ·
**B**(정책 한도 내 자율 서명) = `route_after_cashflow`의 상한·하한·승인 경계 ·
**C**(A2A 협상) = 두 에이전트 그래프의 왕복.

## 직접 돌려보기

로컬 재현은 라이브와 **같은 코드, 같은 도커 이미지**로 돕니다. 다른 것은 아래 표의 재료뿐인데 —
공통점은 전부 "**남의 것을 빌려 쓸 수 없는 것**"(자격증명·자금이 든 지갑·관리형 인프라)이라
로컬 대체물로 갈아 끼웠다는 점입니다. 협상 갈림길·온체인 결제·검증 로직은 동일합니다.

| 구성 요소 | 라이브 (Cloud Run) | 로컬 재현 | 왜 다르게 두었나 |
|---|---|---|---|
| API · 결제 서비스 | Cloud Run 서비스 2개 | **같은 Dockerfile로 직접 빌드** | 다르지 않습니다 — 코드 경로 동일 |
| AI 판단 | Vertex AI Gemini (서비스 계정) | 기본 **규칙 판단**(키 불필요) · 선택: 자기 AI Studio 키 | Vertex는 GCP 프로젝트·자격증명이 필요해 요구가 큽니다. 규칙 모드는 같은 갈림길을 지나고 **판단 근거 문장만** 다릅니다 |
| 블록체인 | devnet (공개 테스트넷) | **localnet** (자기 컴퓨터 속 체인) | devnet 결제엔 자금 있는 지갑이 필요한데 우리 키를 드릴 수 없으니, 무한 에어드랍 되는 로컬 체인을 씁니다 |
| 지갑 · USDC | Secret Manager의 키 · **Circle 공식 devnet USDC** | `make localnet-setup`이 **새로 생성·발행** | 진짜 키는 저장소에 없고(보안), 로컬 체인엔 공식 민트가 없어 직접 발행합니다 |
| DB | Cloud SQL (PostgreSQL 16) | `postgres:16` 컨테이너 | 관리형이냐 컨테이너냐 차이일 뿐 — 같은 엔진, 같은 스키마, 같은 store 코드 |
| 실행 주기 | Cloud Scheduler가 10분마다 | `demo.py` 1회 압축 재생 | 심사가 10분을 기다릴 필요 없이 협상 6종을 한 번에 봅니다 (`make tick`으로 루프도 가능) |
| 시세 구매 | **자가 지수 기본**(우리 데이터 상점, devnet 실결제) · pay.sh 샌드박스는 폴백 | 꺼짐 | pay CLI가 x86_64 전용이라 Apple Silicon 호환을 위해 껐습니다 — 시세는 없어도 조달이 계속되는 선택 재료입니다 |

(운영과 완전히 동일한 Vertex 판단이 굳이 필요하면 `docker-compose.vertex.yml` 오버레이가 있습니다 — GCP 프로젝트 보유자용 선택사항.)

가장 빠른 검증(체인 불필요): `make setup && make test` — 137개, 3초.

**경로 A — Docker (권장, 설치 최소)** · 필요한 것: **Docker** · **Solana CLI**

> 없다면 — [Docker Desktop](https://docs.docker.com/get-docker/) ·
> Solana CLI는 공식 스크립트 한 줄: `sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)"`
> (지갑 생성·로컬 체인·토큰 발행 명령이 함께 설치됩니다 — 저장소가 쓰는 건 이 네 가지뿐:
> `solana-test-validator` · `solana-keygen` · `solana` · `spl-token`)
라이브(Cloud Run)와 **같은 이미지 2개** + PostgreSQL이 컨테이너로 뜨고, 체인만 호스트에서 돕니다
(공식 validator 이미지가 amd64 전용이라 Apple Silicon 호환을 위해 체인은 네이티브로 둡니다).

```bash
make chain            # 터미널 1 — 로컬 블록체인
make localnet-setup   # 터미널 2 — 첫 1회: 지갑 생성·SOL·로컬 USDC (.env 자동 기록 — compose가 지갑 경로를 이어받습니다)
docker compose up --build                 # DB + 결제 + API → http://localhost:8080
docker compose exec api python demo.py    # 협상 6종 — 온체인 결제 포함 완주
```

기본은 규칙 기반 판단(키 불필요)입니다. **자기 키로 진짜 Gemini 판단**을 보려면 —
[AI Studio](https://aistudio.google.com/apikey)에서 무료 키를 받아 스택을 gemini 모드로 다시 올립니다:

```bash
docker compose down                        # mock으로 떠 있던 스택 내리기
GOOGLE_API_KEY=<발급받은 키> SOLPLY_LLM=gemini docker compose up -d
docker compose exec api python demo.py     # 무료 티어 분당 한도 때문에 수 분 걸립니다
```

차이는 **판단 근거 문장**에서 보입니다 — 청구서 타임라인의 본사 심사 사유와 마지막 정산 리포트가
규칙 템플릿이 아니라 LLM이 상황을 읽고 쓴 문장이 됩니다. 협상 갈림길 자체는 같습니다.

**경로 B — 전부 호스트에서 (개발용)** · 추가로 **uv** · **Node 20+** 필요.
첫 실행이면 `make dev`가 지갑 생성 → 에어드랍 → 로컬 USDC 발행까지 스스로 합니다.

```bash
make setup     # 의존성 (backend: uv · payments: npm)
make db        # PostgreSQL 기동 (:5432) — 없으면 Docker로 띄웁니다
make dev       # 블록체인 + 결제 서비스 + API/대시보드 → http://localhost:8080

# 다른 터미널에서 — 협상 6종을 처음부터 끝까지
make demo-mock # 규칙 기반 판단(빠름). 온체인 결제는 실제로 발생합니다
make demo      # Gemini 판단 — backend/.env에 GOOGLE_API_KEY 한 줄 (AI Studio 무료 발급)

make tick      # 경제 루프 한 바퀴 (판매→카드정산→조달→재입고→예약납부)
make test      # 137개
make help      # 전체 명령
```

확인한 환경: macOS 15 (Apple Silicon) · Docker 29 · Solana CLI(Agave) 4.1 — 컨테이너 안은
이미지에 고정되어 어디서나 같습니다 (Python 3.13 · Node 24 · postgres:16).
Apple Silicon 참고: pay.sh CLI가 x86_64 전용이라 로컬 컨테이너에선 **시세 구매만 건너뜁니다**
— 조달 흐름은 동일하고, 라이브(Cloud Run·amd64)에서는 켜져 있습니다.

**개발은 로컬넷, 시연은 devnet.** `make localnet` / `make devnet`으로 전환합니다.
환경 변수는 `backend/.env.example` · `payments/.env.example` 참고
(핵심은 `LLM_PROVIDER`(gemini|vertex|mock) · `SOLPLY_STORE`(local|postgres) · `SOLANA_NETWORK`).
**`LLM_PROVIDER=mock`이면 LLM 없이도 6종이 완주합니다** — 판단 규칙이 `llm/rules.py`에 따로 있어서,
API 키 없이도 온체인 결제까지 그대로 검증할 수 있습니다.

## 클라우드 배포 — 라이브는 이 저장소의 Docker 이미지 그대로입니다

| 서비스 | Dockerfile | 배포 |
|---|---|---|
| `solply-api` (공개) | `./Dockerfile` — 컨텍스트는 **레포 루트** (대시보드 포함). pay.sh가 GLIBC 2.39를 요구해 `python:3.13-slim-trixie` 고정 | `gcloud run deploy solply-api --source . --clear-base-image --region us-central1` — **반드시 루트에서** |
| `solply-payments` (비공개) | `payments/Dockerfile` — 지갑 키를 쥔 유일한 프로세스. **Solana SDK**(`@solana/web3.js`)로 USDC 전송·서명을 코드에서 직접 실행 — 에이전트가 사람 없이 결제하는 손이 이것 | `--no-allow-unauthenticated` — 백엔드 서비스 계정만 호출 가능 |

Cloud SQL · Secret Manager · Scheduler(10분 틱) 구성과 배포 중 겪은 문제들은
[클라우드·pay.sh 구축 기록](docs/cloud-paysh-report.html)에 있습니다.
심사용 데모 장면 재생성은 `gcloud run jobs execute solply-demo --region us-central1` 한 줄입니다.

로컬 실행은 위의 `make` 흐름을 쓰세요. 이미지 두 개에는 API·결제 서비스만 담겨 있는데,
로컬에서는 결제가 붙을 블록체인(로컬넷)이 하나 더 필요하고 그건 도커가 아니라 호스트의
Solana CLI(`solana-test-validator`)로 띄우기 때문입니다 — `make dev`가 체인·결제·API를 한 번에 올립니다.
(클라우드에서는 공개 devnet에 접속하므로 이미지 두 개로 충분합니다.)

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

설계 의도는 [제품 설계](docs/product-design.md)와 [의사결정 로그](docs/decision-log.md)에 있습니다 —
왜 프레임워크를 둘 쓰는지, 왜 재고를 저장하지 않는지까지.

## 오류 수정사항

라이브를 계속 운영하며 발견한 문제와 수리 기록입니다.

- **8/11** — 마진 구조상 매출의 26%가 본사에서 지점으로 영구 이동해 본사 유동성이 고갈되고 카드정산이 멈추던 문제 수리 — 정산 지급 때 로열티(정책, 기본 25%)를 원천징수해 환류 ([`069ffaa`](../../commit/069ffaa))
- **8/8** — 거부된 청구서가 사람 큐에 오르지 않아 "사람에게 넘긴다"가 말뿐이던 문제 수리, 신용점수가 연체를 반영하지 않던 문제 수리 ([`915d6cc`](../../commit/915d6cc), [`d797912`](../../commit/d797912))
- **8/7** — 재고 고갈 지점이 발주 게이트에 갇혀 회복하지 못하던 사망 나선 수리 ([`d4c988e`](../../commit/d4c988e), [`01ab4e9`](../../commit/01ab4e9))
- **8/7** — 카드정산이 고정 순서로 지급돼 첫 지점이 환류를 독식하던 문제 수리 ([`00eea54`](../../commit/00eea54))
- **8/6** — 마진 없는 가격 구조 + 카드정산 중단으로 지점 지갑이 본사로 쏠려 마르던 문제 수리 ([`3a68be1`](../../commit/3a68be1))
- **8/2** — setup과 `docker compose`를 다른 터미널에서 실행하면 자금 없는 지갑이 마운트되던 문제 수리 ([`8c052f3`](../../commit/8c052f3))
- **7/29** — 새 DB에서 "잔액 부족 → 유예 협상" 시나리오의 전제가 성립하지 않던 문제 수리 ([`f4a4535`](../../commit/f4a4535))

## 더 읽을 것

[제품 설계](docs/product-design.md) · [수익 모델](docs/revenue-model.md) · [의사결정 로그](docs/decision-log.md) ·
[클라우드·pay.sh 구축 기록](docs/cloud-paysh-report.html) · [영상 대본](docs/video-script.md) ·
[해커톤 맥락](docs/hackathon-context.md) · [지점 간 직거래 설계](docs/store-to-store-design.md) ·
[작업 계획](docs/wbs.md) · [제출 체크리스트](docs/checklist.md)
