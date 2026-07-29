# 인수인계 — 다른 세션에서 이어받을 때 먼저 읽는 문서

> 마지막 갱신: **2026-07-28 밤** · 저장소 `github.com/poi2507/solply` (private)
> 프로젝트 배경은 [README](../README.md), 작업 규칙은 [CLAUDE.md](../CLAUDE.md),
> 작업 계획은 [wbs.md](wbs.md).

## 30초 요약

**Solply** — 프랜차이즈 본사·가맹점 식자재 대금(물대)을 AI 에이전트들이 청구·검증·협상·결제·정산까지 사람 개입 없이 처리한다. GCP × Solana AI Agentic 해커톤 출품작.

**제출 마감 8/3 23:59 KST.** 파이널리스트 발표 8/7, 데모데이 8/21.

지금 상태: **데모 6종(정상·차감 협상·P2P 직거래·거부·유예→예약 실행·분할 역제안)이 devnet에서 x402 왕복으로 처음부터 끝까지 돌아간다.** 실제 온체인 USDC 결제가 발생하고(가맹점→본사, 가맹점→가맹점 모두), explorer 링크가 살아 있고, 신용점수가 이력에서 계산되어 데모 중에 오르고, ADK 어시스턴트가 대화로 조회·승인을 대신 누른다. GCP 결제도 풀려 **Vertex AI + $300 크레딧**으로 돌고 있다. 대시보드는 역할(본사·가맹점·관리자)이 분리되고, 청구서 행을 펼치면 협상 전 과정이 한 흐름으로 보인다. **막힌 항목이 없다.** 남은 건 **Cloud Run 배포(라이브 URL)**, 영상, 제출물 마감.

---

## 🔴 내일(7/30) 회사 맥에서 — 환경 재현 + 남은 일

> **7/29 밤(집 맥)에 배포까지 끝났다.** 라이브 URL·클라우드 자원은 §2 표 참고.
> 남은 일은 §3 영상 대본, §4 README, §5 public 전 점검 — 코드 작업은 사실상 끝.

### 0. 환경 재현 — 전부 git과 gcloud에서 내려받는다 ⏱️15분

비밀값은 이제 **git(코드·문서) 아니면 Secret Manager(지갑 키·DB 비번)** 둘 중 하나에 있다.
집 맥에서 뭘 복사해 갈 필요가 없다.

**① 코드**
```bash
cd ~/workplace/solply && git pull        # 회사 맥 경로
cd backend && uv sync && cd ..           # 의존성 추가 없음 — import 에러 날 때만
```

**② gcloud 로그인** (Vertex·배포·Job 실행·시크릿 전부 이걸로)
```bash
gcloud auth login                        # poi2507.dev@gmail.com
gcloud config set project gen-lang-client-0014864033
gcloud auth application-default login    # 로컬에서 Vertex 호출할 때 쓰는 ADC
```

**③ 지갑 키 — devnet 자금이 든 키인지 먼저 확인**
```bash
for w in hq store-a store-b store-c; do
  printf "%-8s %s\n" $w "$(solana-keygen pubkey ~/.config/solana/solply/$w.json)"
done
```
기대값 (이 주소들에 devnet SOL·USDC가 있다):
```
hq       HzQ9FXdXTPmLVs1Q4J89FGqq6zKUFdXbje5EBfX3gdDJ
store-a  6hWEQwgw7qtC4ducWLbfbVL7JrqMnzzDUsfj82EXwjmk
store-b  NEcdWbM14tmkwX1ctS2fwcL3Min2vgsebfD4CwfYLu8
store-c  Fjfd2FjKPDBYtBonZh69AfCVLv3bkwtkbGuwSydy33JD
```
다르거나 없으면 Secret Manager에서 내려받는다:
```bash
mkdir -p ~/.config/solana/solply && chmod 700 ~/.config/solana/solply
for w in hq store-a store-b store-c; do
  gcloud secrets versions access latest --secret=solply-wallet-$w > ~/.config/solana/solply/$w.json
done
chmod 600 ~/.config/solana/solply/*.json
```

**④ backend/.env** — 아래 값들은 비밀이 아니라서 여기 그대로 적는다. 회사 맥의 기존
.env와 대조해서 다른 줄만 맞추면 된다 (`GOOGLE_API_KEY`는 vertex 경로에선 안 쓴다 —
있으면 그대로 둔다):
```
LLM_PROVIDER=vertex
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=gen-lang-client-0014864033
GOOGLE_CLOUD_LOCATION=us-central1
HQ_MODEL=gemini-3.6-flash
STORE_MODEL=gemini-3.5-flash-lite
SOLANA_NETWORK=devnet
SOLPLY_STORE=postgres
AGENT_SPEND_LIMIT_USDC=50
```

**⑤ payments/.env** — `make devnet`/`make localnet`이 관리한다. 파일 자체가 없으면:
```
SOLANA_RPC_URL=https://api.devnet.solana.com
SOLANA_NETWORK=devnet
USDC_MINT=4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU
PORT=3000
```

**⑥ 확인**
```bash
make db && make dev            # ⚠️ 이건 localnet으로 되돌린다 — devnet이면 make devnet && make pay
make demo-mock                 # 6종 완주하면 환경 동일
```

**클라우드는 재현할 게 없다** — 라이브 URL은 어디서나 열리고, 데모 재생성도 gcloud만 있으면 된다:
```bash
gcloud run jobs execute solply-demo --region us-central1
```
DB 비밀번호가 필요한 건 백엔드 재배포(env의 DATABASE_URL) 때뿐이다:
```bash
gcloud secrets versions access latest --secret=solply-db-pass
```

### 1. 새 대시보드 화면 확인 ✅ (7/29 회사 맥에서 완료 — 라이트 전환까지)

### 2. Cloud Run 배포 ✅ 완료 (7/29 밤, 집 맥)

**라이브 URL: https://solply-api-965647250280.us-central1.run.app**

| 자원 | 이름 | 비고 |
|---|---|---|
| Cloud Run 서비스 | `solply-api` (공개) | FastAPI+대시보드+에이전트. 루트 `Dockerfile` (frontend 포함) |
| Cloud Run 서비스 | `solply-payments` (**비공개**) | 지갑 키 보유. backend SA만 `run.invoker` |
| Cloud Run Job | `solply-demo` | 같은 이미지로 demo.py 실행 — **심사용 화면을 언제든 재생성** |
| Cloud SQL | `solply-db` (Postgres 16, us-central1) | 커넥터(`/cloudsql/...`)로 연결 |
| Secret Manager | `solply-wallet-{hq,store-a,b,c}` | 지갑별 디렉터리로 마운트 |
| 서비스 계정 | `solply-backend` / `solply-payments` | vertex·sql·invoker / secret 접근 |

라이브 데모 재실행: `gcloud run jobs execute solply-demo --region us-central1`
(Vertex 판단 + devnet 결제가 전부 클라우드 안에서 돈다. 새 이미지 배포 후에는
`gcloud run jobs update solply-demo --image <새 이미지>` 먼저.)

재배포(백엔드): 레포 루트에서 — **반드시 루트에서**. backend/에서 돌리면 Dockerfile을
못 찾고 buildpack으로 빠져 죽은 리비전이 생긴다 (7/29에 실제로 겪음, rev 00003).
```bash
gcloud run deploy solply-api --source /절대/경로/레포루트 --clear-base-image --region us-central1 ...
```
전체 명령은 커밋 `2ea1188` 메시지와 이 파일의 git 이력에 있다. DB 비밀번호는
`~/.config/solply-cloudsql-pass` (집 맥, git 밖).

**배포에서 배운 것 (코드에 반영됨):**
- Cloud Run은 한 디렉터리에 시크릿 하나 → `loadKeypair`가 `<dir>/hq/hq.json` 폴백 지원
- 비공개 서비스 호출은 ID 토큰 필요 → `app/solana/payments.py`가 메타데이터 서버에서
  받아 붙인다 (로컬엔 메타데이터 서버가 없어 자동으로 무인증 — 개발 흐름 불변)
- **시나리오 C의 전제가 로컬 DB의 사용자 정책(min_reserve=10)에 숨어 있었다** —
  새 DB에선 기본값 2라 C가 그냥 결제해버림. `align_balance("store-c", 4.0)`로
  어떤 정책값에서도 전제가 성립하게 고정 (커밋 `f4a4535`)

### ★ 7/30 본체 — 라이브 경제 루프 (판매·발주·재입고 틱) ⏱️4~5시간

7/29 밤 사용자 결정: 업장은 손님에게 팔아 수익을 얻고, 본사는 납품으로 수익을 내고,
창고가 비면 지출하며 채운다 — **경제가 스스로 돈다.** 스케줄러가 주기적으로 굴린다.

**왜 지금**: 라이브 URL이 "과거 데모의 기록"에서 **"지금 거래 중인 시스템"** 이 된다.
심사자가 언제 열어도 에이전트가 일하고 있다 — 기준 4(실제 구동)를 상시 증명.
WBS 파이널 백로그 "2순위 발주 자동화"를 앞당기는 것 — 원칙도 그대로:
**발주 버튼(사람 트리거)을 만들지 않는다. 사건이 트리거, 사람은 경계에서만.**

**설계 — 틱 하나(POST /api/ticks/run)가 하는 일, 순서대로:**

1. **판매 시뮬** — 지점마다 보유 재고 한도 내에서 몇 개 판매
   → `record_move(store, sku, -n, "sold")` (이미 있는 메커니즘 — E 시나리오의
   "주말 피크 소진"이 정확히 이것) + 매출을 오프체인 장부에 적립
2. **카드정산 지급** — 적립 매출을 hq→지점 온체인 이체(memo `CARD-SETTLEMENT`)로 지급.
   demo.py의 `simulate_card_settlement`가 이미 이 패턴 — **runtime 모듈로 옮겨 공용화**
   (돈 보존: 고객 결제는 카드사 대행 역할의 hq가 지급 — 생태계 총량 80 USDC 불변)
3. **지점 재고 점검·발주** — 안전재고 미달 → 기존 조달 비교 그래프(P2P vs 본사 발주) 재사용.
   본사 발주면 **납품 문서 생성 → 청구서 발행 → 기존 x402 정산 플로우** 그대로
4. **본사 창고 점검·재입고** — `effective_inventory("hq")` 임계 미달 →
   `record_move("hq", +qty, "restocked")` + 지출 이벤트. 원장 기록만 (외부 공급사에
   돈이 새면 총량이 깨진다). 5번째 supplier 지갑 온체인 매입은 스트레치
5. **예약 납부 실행** — 예약일 도래 건을 기존 실행기로. UI에 이미 "운영에선
   Cloud Scheduler가 실행합니다"라고 써놨다 — 그 말이 사실이 되는 순간

**주의 — 코드에서 걸리는 곳:**
- `create_invoice`가 납품을 **fixtures에서만** 읽는다 (`hq/tools.py`) → `deliveries`
  컬렉션도 보게 확장해야 동적 납품이 청구로 이어진다
- **데모 6종 불변**: 틱은 `TICK_ENABLED` 토글로 끌 수 있어야 한다. 촬영·리허설 중
  백그라운드 틱이 상태를 흔들면 안 된다. `db.reset`은 이동을 지우니 시드 복원은 그대로
- 무작위: 판매량 무작위는 화면을 살아있게 하지만, 테스트는 고정 시드로

**스케줄러 배선:**
- 운영: **Cloud Scheduler** → 라이브 URL의 `/api/ticks/run` (10분 간격 정도,
  `gcloud scheduler jobs create http ...`) — GCP 스택 항목이 하나 더 늘어난다 (기준 2)
- 로컬: `make tick` 한 번씩 수동 실행 (개발·검증용)

### 3. 영상 대본 (4.5) ⏱️1시간

3분 컷. wbs가 정한 배분: **A 15초 압축 → B 45초 → E 60초 → C 40초**, D(거부)는 로그로 스치듯.
`--only b` 식으로 장면별 실행. 어시스턴트 장면은 Vertex 전환 후라 데모와 같이 찍어도 된다.
경제 루프가 들어가면 오프닝을 "지금도 돌고 있는 라이브 화면"으로 시작하는 컷도 고려.

### 4. README 정비 (4.9) ⏱️40분

심사자가 clone → 실행까지 따라올 수 있게. brew 없는 맥 우회 설치는 넣지 말고(우리 사정),
`make db && make dev && make demo-mock` 한 줄기만 남긴다.

### 5. public 전환 전 점검 ⏱️30분 (4.10 + DB 백로그 3)

- `.env` 커밋 이력 재확인 — 실제 키 값으로 그렙할 것. `AIza`로 찾으면 안 걸린다(키가 `AQ.`로 시작).
- `db/postgres_store.py`의 `list_docs` 필터 **키** f-string 삽입 → 화이트리스트 한 줄.
  내부 호출뿐이라 실제 위험은 없지만 public 레포에서 인젝션 모양으로 읽힌다.

### 7/30 시간 배분 제안

| 시간 | 할 일 | 비고 |
|---|---|---|
| 오전 | §0 환경 재현(15분) → ★경제 루프 코어 (판매 틱·발주 연결) | `create_invoice` fixtures 의존부터 풀 것 |
| 오후 | ★스케줄러 배선·라이브 반영 → §3 영상 대본 | **15시까지 루프가 안 끝나면 접고 대본으로** — 루프는 가산, 영상은 필수 |
| 저녁 | §4 README → §5 public 전 점검 → devnet 리허설 | 촬영 전 마지막 코드 수정 기회 |

### 3. 사용자 — 제출물 (8/1~)

- **소개서 다듬기(4.8)**: [pitch.html](pitch.html) 12장 초안 완성돼 있음 — 표지·마지막 장의
  **팀명·라이브 URL·영상 URL만 비어 있다**. `open docs/pitch.html` → Chrome 인쇄 →
  PDF 저장(여백 없음 + 배경 그래픽 체크) = 벡터 PDF.
- **영상 촬영(8/1~2)**: 장면별 `--only`로. 어시스턴트 장면은 무료 티어 한도 때문에
  데모와 **따로** 찍을 것 (Vertex 전환 후엔 무관).
- 수익모델은 ✅ 확정 — [revenue-model.md](revenue-model.md) (3층: 구독 → P2P 중개료 → 온체인 여신).
  가맹점 수 통계(약 35만)만 제출 전 재확인.

### 7/28 밤(집 맥)에 끝난 것

- **GCP 결제 해결** — 미납 ₩16,000 때문에 결제 계정이 닫혀 콘솔 목록·드롭다운에서 아예
  숨겨져 있었다(그래서 "표시할 항목이 없음"). 입금 → 계정 재개 → **$300 크레딧 전액 재지급**.
  `LLM_PROVIDER=vertex`로 전환 완료, 어시스턴트도 `factory.model_for("hq")`를 쓰게 고쳤다.
- **devnet 전환** — 지갑 4개 SOL·USDC 수령, **USDC 토큰 계정(ATA) 사전 생성**
  (첫 전송 때 만들면 devnet에서 수 초가 더 걸려 데모가 타임아웃된다), 6종 완주 확인.
  데모 금액을 1/5로 낮췄다(청구 7 USDC, 자동결제 상한 10, 최소 잔액 2) — faucet이 한 번에
  20씩만 주기 때문이다. 심사에서 보는 건 금액이 아니라 플로우다.
- **PostgreSQL 이관** — conda Postgres에 zoneinfo가 없어 JDBC 클라이언트(DBeaver)가
  `Asia/Seoul` 요청을 **거부**당했다(경고가 아니라 연결 실패) → 시스템 zoneinfo 심볼릭 링크.
  풀에 `check=ConnectionPool.check_connection`을 달아 DB 재시작 후 죽은 커넥션을 걸러낸다.
- **역할 분리 대시보드** — 본사/가맹점/관리자가 서로 다른 화면과 권한을 본다(`frontend/role.js`).
- **화면 재설계** — 같은 무게의 카드 아홉 개를 걷어내고 청구서 표를 화면의 중심으로.
  행을 누르면 그 청구서의 협상 전 과정이 펼쳐진다(`GET /api/invoices/{id}/timeline`).
  **아직 브라우저로 눈으로 본 적이 없다** → §1이 내일 첫 할 일.

### 7/28 회사 맥에서 끝난 것 (요약)

- **Phase 1** x402 에이전트 연결 · **Phase 2** 신용 실계산·거부·예약 실행 · **Phase 2.5** P2P 직거래
  · **Phase 2.7** 이중결제 가드·사람 승인·멀티턴 분할·정산 리포트
- **대시보드 운영 3종**: 정책 변경 증빙(`policy.updated`, actor=human) · 예약 "지금 실행" 버튼
  (입금 시뮬 포함, Cloud Scheduler는 본문 없이 호출 시 실잔액 실행) · 가맹점 카드 재고 칩
- **ADK 어시스턴트**: 대시보드 채팅 — 조회·승인·예약 실행을 대화로. 역할 분담이 설계 결정:
  **LangGraph=거래 두뇌(감사 가능한 그래프), ADK=사람 창구(도구 호출)**. mock 모드에선 503.
- 촬영 전 수정 3건(미수금 이중계산·mock 중복 출력·분할 회차 402), 낡은 HTML 문서 3개 삭제,
  `make test` 임시 저장소 격리(라이브 DB 안 더럽힘), 테스트 **99개**
- **심사 Q&A 라이브 카드**: 정책 UI에서 자동결제 상한을 **5 USDC**로 낮추고 `--only a` → 에이전트 멈춤 →
  승인 패널 → 버튼 → 이어서 결제. 어시스턴트에게 "승인 대기 있어? 승인해줘"로도 같은 흐름.
- 데모는 자기 유지된다(카드정산 입금 시뮬 + db.reset이 재고도 시드로 복귀) — 리허설 무제한.
- 주의: Gemini 무료 티어에서 `make demo`와 어시스턴트를 **동시에** 쓰면 429 가능 (경로가 둘).

---

## 1. 로컬 환경 되살리기

세 개의 서버가 필요하다. 순서대로:

```bash
cd ~/workspace/gcp-solana-agentic-hackathon   # 집 맥 (메인) — 회사 맥은 ~/workplace/solply

make db      # PostgreSQL (:5432) — 데이터가 여기 있다
make dev     # 블록체인(:8899) + 결제(:3000) + API/대시보드(:8080)
```

`make dev`는 validator를 띄우고 지갑·USDC까지 세팅한 뒤 세 서버를 붙인다. 대시보드는 http://localhost:8080.

데모 실행 (다른 터미널):

```bash
make demo-mock   # 규칙 기반, 몇 초 — 개발·리허설용 (온체인 결제는 실제로 발생)
make demo        # Gemini 판단, 10분+ — 심사·영상용
make test        # 17개 테스트
make help        # 전체 명령
```

### 작업 머신 2대 (7/27부터)

**집 맥이 메인**(최종 작업·devnet 시연·제출), 회사 맥은 낮 시간 보조 개발용이다.

**① 집 맥 — macOS 13.5 Intel, Homebrew 죽음.** 레포 `~/workspace/gcp-solana-agentic-hackathon`. 전부 공식 인스톨러로 우회 설치, `~/.zshrc`의 `# gcp-solana-hackathon-paths` 블록에 PATH 등록. **여기서는 brew 쓰지 말 것** — 공식 인스톨러나 conda-forge.

| 도구 | 위치 |
|---|---|
| Node 24 | `~/.local/node/bin` |
| uv | `~/.local/bin` |
| Solana CLI 4.1 | `~/.local/share/solana/install/active_release/bin` |
| gcloud SDK | `~/.local/google-cloud-sdk` |
| gh CLI | `~/.local/bin/gh` (poi2507 로그인됨) |
| PostgreSQL | `~/.local/pg-env/bin` (conda-forge), 데이터 `~/.local/pgdata` |

원본 지갑 키(`~/.config/solana/solply/`)와 `GOOGLE_API_KEY`가 든 `backend/.env`는 **집 맥에만 있다.**

**② 회사 맥 — Apple Silicon, Homebrew 정상 (7/27 환경 구축).** 레포 `~/workplace/solply`. uv·Solana CLI는 공식 인스톨러(집 맥과 같은 경로), Node·PostgreSQL 17·gh는 Homebrew. gcloud 미설치. 지갑은 **로컬넷 전용으로 새로 생성**(devnet 코인 받는 주소 아님). `GOOGLE_API_KEY`는 집 폴더 복사본(`~/workplace/gcp-solana-agentic-hackathon`)에서 가져와 설정 완료(7/27, 유효성 확인됨) — `make demo`(Gemini)도 동작한다. Docker가 8000 포트를 점유해 validator gossip을 8010으로 옮겼다(`dev.sh`·`Makefile`에 반영, 집 맥에서도 무해).

---

## 2. 지금 무엇이 되고 무엇이 안 되나

| 항목 | 상태 |
|---|---|
| 로컬넷 + 지갑 4개 + 자체 USDC | ✅ |
| USDC 전송 · memo · 온체인 3중 검증 | ✅ |
| 본사/가맹점 에이전트 (도구 각 7개) | ✅ |
| A지점 정상 결제 / B지점 차감 협상 / C지점 유예 협상 | ✅ 전부 완주 |
| FastAPI 대시보드 + SSE 실시간 반영 | ✅ |
| x402 402 챌린지 + 정산 확정 | ✅ 엔드포인트는 동작 |
| PostgreSQL 저장소 | ✅ |
| mock LLM 리허설 모드 | ✅ |
| **LangGraph 전환** (graph/node/state 분리) | ✅ 2026-07-27 |
| **프롬프트 md 분리** (`<agent>/prompts/*.md`) | ✅ |
| **거래 정책 DB화 + 프론트 설정 UI** | ✅ 상한·하한을 사용자가 설정, 즉시 판단에 반영 |
| Vertex AI 전환 (크레딧·한도 해방) | ⏸ 패키지·분기·점검 스크립트는 준비됨. **gcloud 인증과 결제만 남음** → `make vertex-check` |
| **x402를 에이전트 플로우에 실제 연결** | ✅ 2026-07-27 — 402 챌린지 → 조건 선택 → 결제 → PAYMENT-SIGNATURE 제출 → 정산 확정. 유예도 402 조건 선택으로 서사 연결. `tests/test_x402_flow.py` |
| **온체인 신용점수 실계산** | ✅ 2026-07-28 — `core/credit.py`. 시드 이력 + 이번 세션 정산이 점수에 반영, 대시보드에 근거(정시납·연체·분쟁) 표시. 88/81/92는 이제 계산 결과다 |
| **이상 청구 거부 시나리오 (D)** | ✅ 2026-07-28 — 발주 목록에 없는 품목(DEL-004 랍스터) 감지 → 거부 → 사람 에스컬레이션 |
| **예약 납부 실행** | ✅ 2026-07-28 — `POST /api/schedules/{id}/run` + 데모가 시간을 당겨 실행. C지점이 `settled`까지 간다 |
| **가맹점 간 직거래 (시나리오 E)** | ✅ 2026-07-28 — B 재고 소진 → 조달 비교 → A와 협상 → **본사 승인** → B→A x402 온체인 결제 → 장부 기록. 트랙 C 커버 |
| **멀티턴 역제안 (시나리오 F)** | ✅ 2026-07-28 — 전액 유예 불가 → 본사가 분할 2회 역제안(실제 분할 청구서 발행) → 가맹점 재평가 → 1회차 x402 결제·2회차 예약 |
| **사람 승인 (human-in-the-loop)** | ✅ 2026-07-28 — 상한 초과로 멈춘 결제를 대시보드에서 승인/반려. 승인하면 에이전트가 이어서 결제(라이브 검증 완료). 사람 개입은 actor=human으로 증빙 |
| **이중 결제 방지** | ✅ 2026-07-28 — paid/settled 청구서 재결제 차단 (재시도·중복 호출 안전) |
| **정산 리포트 (Gemini)** | ✅ 2026-07-28 — `/api/report` + 대시보드 버튼 + 데모 마무리. mock은 규칙 조립, Gemini는 자연어 생성 |
| **정산 어시스턴트 (ADK)** | ✅ 2026-07-28 — 대시보드 채팅. ADK Agent가 사람 권한 도구 8개(조회·승인·반려·예약 실행)로 대화 응대. **역할 분담: LangGraph=거래 두뇌, ADK=사람 창구.** mock 모드에선 비활성(503) |
| **Cloud Run 배포** | ❌ |
| **devnet 전환** | ❌ 지금은 로컬넷 |
| **소개서 초안** | ✅ 2026-07-28 — [pitch.html](pitch.html) 12장. 남은 것: 표지·마지막 장의 팀명·URL 채우기, 사용자 다듬기(4.8) 후 PDF 내보내기 |
| **데모 영상** | ❌ 8/1~2 촬영 예정 (대본은 devnet 전환 후) |
| **수익모델** | ✅ 2026-07-28 — 3층 구조(구독·P2P 중개료·온체인 여신) 확정, [revenue-model.md](revenue-model.md) |

---

## 3. 남은 일정

> 상세 작업 분해는 [wbs.md](wbs.md) — 25개 항목, 담당·의존성·크리티컬 패스·리스크.

| 날짜 | 목표 | 담당 |
|---|---|---|
| 7/28 (월) | 에이전트가 x402로 대화 · 신용점수 실계산 착수 | 🤖 |
| 7/29 (화) | 데모 4종·예약 실행 → 오후 P2P 착수 | 🤖 |
| 7/30 (수) | **시나리오 E (가맹점 간 직거래) 완주** · **GCP 결제 해결** | 🤖 👤 |
| **7/31 (목)** | **Cloud Run 배포** — 라이브 URL(가산점) | 🤖 |
| **8/1 (금)** | **devnet 전환 + 데모 영상 3분** | 🤖 👤 |
| 8/2 (토) | 소개서 PPT (타깃·문제·**수익모델**·아키텍처) | 🤝 |
| **8/3 (일)** | README 정비, **레포 public 전환**, 23:59 전 제출 | 👤 |

### 사용자(taewoong) 작업 — 기한 순

| 기한 | 할 일 | 왜 |
|---|---|---|
| **7/28** | Discord 가입 + devnet SOL 요청 | 답변 지연 리스크. 없으면 explorer 링크 없는 데모가 된다 |
| **7/28** | devnet USDC 수령 (faucet.circle.com) | 즉시 가능. store-a·b만, **c는 제외** |
| **7/30** | GCP 결제 카드 교체 | 라이브 URL(가산점). 안 되면 포기 가능 |
| **8/1** | 수익모델 확정 | 소개서 필수 항목 |
| **8/2** | 데모 영상 촬영 (대본은 Claude가 준비) | 3분 이내 |
| **8/3** | 최종 제출 | 마감 23:59 |

**참고**: GCP $300 크레딧은 **Gemini API에 못 쓴다**(주최측 명시, 별도 시스템). Gemini는 AI Studio 무료 티어로 이미 동작 중이므로, 크레딧은 Cloud Run 배포에만 필요하다.
Discord `#pay-sh-질문` 채널에 Solana Foundation 개발자(Ludo)가 한/영으로 직접 답변한다.

---

## 4. 아키텍처 요약

```
backend/app/
├── main.py        FastAPI 조립 (API + x402 + 프론트 서빙, 컨테이너 1개)
├── config.py      환경변수는 여기서만 읽는다
├── api/           dashboard.py(+SSE) · policy.py(정책 설정) · x402.py
├── agents/        state.py(BaseState) · runner.py(실행기) · prompts.py(md 로더) · utils.py
│   ├── hq/        graph.py · node.py · state.py · tools.py · prompts/{role,task,policy,output}.md
│   └── store/     (동일 구조)
├── core/          protocol.py(x402) · policy.py(거래 정책) · fixtures.py
├── db/            store.py(파사드) → local_store.py | postgres_store.py
├── llm/           factory.py(gemini|vertex|mock) · judge.py(판단) · rules.py(mock 규칙)
└── solana/        payments.py (TS 결제 서비스 HTTP 클라이언트)

frontend/          빌드 없는 정적 대시보드 (FastAPI가 /assets로 서빙)
payments/          TypeScript — Solana USDC 전송·검증 (Solana SDK가 JS라서 분리)
```

### 지켜야 할 규칙

- 환경변수는 `config.py`에서만. 다른 모듈에서 `os.getenv` 직접 호출 금지.
- 저장소 접근은 `app.db.store` 파사드로만. local/postgres를 갈아끼운다.
- 프롬프트는 `<agent>/prompts/*.md`에만. role·task·policy·output 네 파일.
  프롬프트에 적는 도구 이름은 실제 함수명과 일치해야 한다 (테스트가 검사).
- 한도·기준 같은 개인별 수치는 md가 아니라 **DB의 정책**에서 주입된다 (`core/policy.py`).
- 에이전트 도구는 부수효과만. 순수 계산은 `utils.py`, 판단은 `llm/judge.py`, 흐름은 `node.py`.
- 결제는 로컬넷/devnet 전용. **메인넷 금지.**

---

## 5. 알려진 함정 (같은 데서 두 번 막히지 않도록)

**Gemini 무료 티어는 모델당 분당 5회.** 에이전트 4대가 도구를 여러 번 부르면 금방 소진된다. 본사는 `gemini-3.6-flash`, 가맹점은 `gemini-3.5-flash-lite`로 나눠서 한도를 분산해뒀고(한도가 모델별로 따로 걸린다), `runner.py`가 429를 잡아 재시도한다. 그래도 `make demo`는 10분 이상 걸리니 **개발 중에는 `make demo-mock`을 쓸 것.**

**`gemini-2.5-flash`는 신규 사용자에게 제공되지 않는다.** 3.x 계열을 써야 한다.

**Memo 프로그램 주소는 `MemoSq4gqABAXKb96qnH8Tys...`** — `Tys`의 s가 소문자다. 대문자로 적으면 "계정 없음"으로 실패한다. 로컬넷에는 이 프로그램이 없어서 메인넷에서 `--clone`으로 가져와야 하고, `make chain`과 `scripts/dev.sh`에 반영돼 있다.

**가맹점 USDC가 떨어지면 결제가 조용히 실패한다.** 데모를 여러 번 돌리면 소진되니 보충:
```bash
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"
MINT=$(grep '^USDC_MINT=' payments/.env | cut -d= -f2)
HQ=~/.config/solana/solply/hq.json
spl-token mint "$MINT" 100 --recipient-owner "$(solana-keygen pubkey ~/.config/solana/solply/store-a.json)" \
  --url localhost --fee-payer $HQ --mint-authority $HQ
```
**단 store-c는 보충하지 말 것** — 잔액이 부족해야 유예 협상 시나리오가 발동한다.

**데모 시나리오는 코드가 아니라 데이터로 만들어진다.** `backend/data/fixtures.json`의 B지점 검수 불일치(닭 10 청구 / 9 입고)와 C지점 신용점수 92, 그리고 지갑 잔액(A·B 넉넉, C 5 USDC)이 시나리오의 전부다. 건드리면 데모가 죽고, `tests/test_core.py`가 이를 지킨다.

**conda Postgres에는 zoneinfo가 없다.** 시스템 타임존(KST-9)을 못 읽어 UTC로 고정해뒀고,
`$PG_HOME/share/zoneinfo`를 `/usr/share/zoneinfo`로 심볼릭 링크했다 (setup-postgres.sh가 처리).
이게 없으면 **DBeaver 등 JDBC 클라이언트가 `TimeZone=Asia/Seoul`을 보내며 연결이 거부된다.**

**DB를 GUI로 보려면** — DBeaver: localhost / 5432 / solply / taewoong / 비밀번호 없음(trust 인증).
테이블은 `documents`(collection·doc_id·data JSONB)와 `events`(append-only 로그) 둘뿐이다.

**Solana validator가 8000번 포트를 쓴다.** FastAPI는 8080을 쓰는 이유. 회사 맥에서는 Docker가 8000을 점유하고 있어 validator gossip 포트를 **8010**으로 옮겼다 (`dev.sh`·`Makefile`에 반영, 집 맥에서도 무해).

**API 키가 `.env.example`에 들어간 적이 있다.** 이 파일은 git에 올라가므로 실제 값은 `backend/.env`에만. **제출 시 레포를 public으로 바꾸므로** 그 전에 한 번 더 확인할 것.

---

## 6. 심사 대응 요약 (발표 준비할 때)

**4대 기준**: 혁신성·UX / AI 활용도(Gemini·GC 스택) / 인프라 연동(USDC·Solana Pay·pay.sh) / **실제 구동**(실행 로그·트랜잭션). 배점 비공개.

**"목업은 심사 대상에서 제외"** — 주최측이 경고 배너로 명시. 데모데이 당일 실제 결제가 동작해야 한다.

**"왜 온체인인가"에 대한 우리 답** (수수료 논거는 약하다 — 금융위가 "초소액 아니면 카드가 쌀 수 있다"고 반론):
1. 에이전트는 은행 계좌를 못 만든다. 카드망은 사람 승인 전제.
2. B2B 외상 30~60일 → 0.4초.
3. 납부 이력이 조작 불가능한 신용이 된다 (여신 자동화로 확장).
4. 본사·가맹점이 같은 장부를 본다 (정산 불신 해소).

**차별화 포인트는 협상.** 다른 팀은 "자동 결제"까지 만들 것이다. 실패 상황에서 에이전트끼리 대안을 제시하고 합의하는 게 우리만의 훅이다.

**시장 정보**: 현재 x402 트래픽은 디지털 재화(데이터·API) 일색이고 **실물 B2B는 공백**이다. "실물 B2B 첫 사례"로 포지셔닝 가능. 단 "왜 아직 아무도 안 했나(실물 이행 리스크·분쟁)"에 답을 준비할 것.

**약점**: 사용자가 프랜차이즈 도메인 경험이 없다. 실제 물대 정산 주기·검수 분쟁 사례를 리서치해서 Q&A를 방어해야 한다.

---

## 7. 문서 지도

| 문서 | 내용 |
|---|---|
| [README.md](../README.md) | 프로젝트 개요, 구조, 실행법 |
| [CLAUDE.md](../CLAUDE.md) | 작업 규칙 (AI가 읽는 것) |
| [product-design.md](product-design.md) | 프로덕트 설계, 에이전트 구성, 데모 시나리오 |
| [decision-log.md](decision-log.md) | 아이디어가 여기까지 온 과정, 기각된 후보들 |
| [kickoff-notes.md](kickoff-notes.md) | 킥오프 발표자료 4종 분석 (일정·x402 스펙·pay.sh) |
| [wbs.md](wbs.md) | 남은 기간 작업 분해, 담당·의존성·리스크 |
| [store-to-store-design.md](store-to-store-design.md) | 시나리오 E(가맹점 간 P2P 직거래) 구현 설계 |
| [checklist.md](checklist.md) | 제출 전 체크리스트 |
