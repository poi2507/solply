# 인수인계 — 다른 세션에서 이어받을 때 먼저 읽는 문서

> 마지막 갱신: **2026-07-27** · 저장소 `github.com/poi2507/solply` (private)
> 프로젝트 배경은 [README](../README.md), 작업 규칙은 [CLAUDE.md](../CLAUDE.md),
> 작업 계획은 [wbs.md](wbs.md), 전체 브리핑은 [briefing.html](briefing.html).

## 30초 요약

**Solply** — 프랜차이즈 본사·가맹점 식자재 대금(물대)을 AI 에이전트들이 청구·검증·협상·결제·정산까지 사람 개입 없이 처리한다. GCP × Solana AI Agentic 해커톤 출품작.

**제출 마감 8/3 23:59 KST.** 파이널리스트 발표 8/7, 데모데이 8/21.

지금 상태: **데모 3종 시나리오가 처음부터 끝까지 돌아간다.** 실제 온체인 USDC 결제가 발생하고, 대시보드에 실시간으로 찍히고, x402 엔드포인트도 동작한다. 남은 건 x402를 에이전트에 연결, 신용점수 실계산, 거부·예약 시나리오, 배포, 그리고 제출물(영상·PPT).

---

## 🔴 다음 세션에서 바로 할 일 (2026-07-28 기준)

### 사용자가 먼저 — 30분이면 끝난다

크리티컬 패스 두 개가 모두 사람 손에 걸려 있다. **이것부터 걸어두고 개발을 시작한다.**

1. **devnet 코인 확보 착수** ⏱️20분 — 유일하게 막히면 프로젝트가 아픈 항목. explorer 링크가 없으면 심사 기준 4에서 크게 잃는다.
   - Discord 가입 → discord.gg/bYrJCUAsj
   - `#일반` 또는 운영 채널에 **devnet SOL 추가 수령 요청** (주최측이 안내한 유일한 공식 경로, 답변에 시간이 걸리니 미리)
   - https://faucet.circle.com 에서 **devnet USDC** — store-a·store-b만. **store-c는 받지 말 것** (잔액 부족이 유예 협상 시나리오)
   - 지갑 주소: hq `HzQ9FXdXTPmLVs1Q4J89FGqq6zKUFdXbje5EBfX3gdDJ` / store-a `6hWEQwgw7qtC4ducWLbfbVL7JrqMnzzDUsfj82EXwjmk` / store-b `NEcdWbM14tmkwX1ctS2fwcL3Min2vgsebfD4CwfYLu8` / store-c `Fjfd2FjKPDBYtBonZh69AfCVLv3bkwtkbGuwSydy33JD`
2. **GCP 결제 해결** ⏱️10분 — 등록된 Mastercard가 체크카드일 가능성이 높다. **신용카드로 교체** 시도. 그래도 ₩16,000 배너가 남으면 입금해도 된다(크레딧으로 적립되며 사라지지 않는다). 7/30까지 결판. 라이브 URL은 가산점이라 최악의 경우 포기 가능.

### Claude가 이어서 — Phase 1부터

[wbs.md](wbs.md)의 Phase 1(x402를 에이전트 플로우에 연결) → Phase 2(신용점수 실계산·거부 시나리오·예약 실행) 순서.

```bash
make db && make dev      # 환경 복구
make demo-mock           # 현재 상태 확인
```

### 사용자가 생각해둘 것 — 수익모델

소개서 PPT 필수 4요소(타깃·문제·**수익모델**·아키텍처) 중 하나인데 아직 없다. 후보:

| 안 | 내용 | 평가 |
|---|---|---|
| 정산 건당 수수료 | 본사에 건당 과금 | 단순하지만 "온체인은 수수료가 싸다"는 우리 논거와 충돌 |
| **SaaS 구독** | 가맹점 수 기준 월정액 | B2B SaaS라 심사위원이 익숙함 |
| 결제규모 bp | 거래액의 0.x% | 스케일하면 크지만 초기엔 미미 |
| **여신 데이터** | 쌓인 신용 이력을 금융사에 판매 | 확장 스토리로 가장 강력, 프라이버시 이슈 있음 |

**추천 조합: SaaS 구독(당장의 수익) + 여신 데이터(미래 비전).** 정해지면 소개서에 반영한다.

### 선택 — 도메인 리서치

Q&A 방어의 유일한 약점. 주변에 프랜차이즈·요식업 종사자가 있으면 10분만 물어볼 것: "물대 정산 주기는? 검수가 안 맞으면 어떻게 처리하나?" 업계 한마디가 리서치 열 페이지보다 세다. 없으면 Claude가 자료로 채운다.

---

## 1. 로컬 환경 되살리기

세 개의 서버가 필요하다. 순서대로:

```bash
cd ~/workspace/gcp-solana-agentic-hackathon

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

### 툴체인 위치 (이 맥은 Homebrew가 죽어 있다)

macOS 13.5 Intel이라 Homebrew가 지원을 끊었다. 전부 공식 인스톨러로 우회 설치돼 있고 `~/.zshrc`의 `# gcp-solana-hackathon-paths` 블록에 PATH가 등록돼 있다.

| 도구 | 위치 |
|---|---|
| Node 24 | `~/.local/node/bin` |
| uv | `~/.local/bin` |
| Solana CLI 4.1 | `~/.local/share/solana/install/active_release/bin` |
| gcloud SDK | `~/.local/google-cloud-sdk` |
| gh CLI | `~/.local/bin/gh` (poi2507 로그인됨) |
| PostgreSQL | `~/.local/pg-env/bin` (conda-forge), 데이터 `~/.local/pgdata` |

**새 도구가 필요하면 brew 쓰지 말 것.** 공식 인스톨러나 conda-forge를 쓴다.

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
| **x402를 에이전트 플로우에 실제 연결** | ❌ 지금은 엔드포인트만 있고 에이전트는 직접 호출 안 함 |
| **이상 청구 거부 시나리오** | ❌ 도구(`refuse_payment`)는 있고 데모에 없음 |
| **예약 납부 실행** | ❌ C지점이 `scheduled`에서 멈춤 |
| **Cloud Run 배포** | ❌ |
| **devnet 전환** | ❌ 지금은 로컬넷 |
| **데모 영상 · 소개서 PPT** | ❌ |
| **수익모델** | ❌ 소개서 필수 항목인데 미정 |

---

## 3. 남은 일정

> 상세 작업 분해는 [wbs.md](wbs.md) — 25개 항목, 담당·의존성·크리티컬 패스·리스크.
> 시각화: `docs/wbs.html`

| 날짜 | 목표 | 담당 |
|---|---|---|
| 7/28 (월) | 에이전트가 x402로 대화 · 신용점수 실계산 착수 | 🤖 |
| 7/29 (화) | 데모 4종(거부 추가) · 예약 실행 | 🤖 |
| 7/30 (수) | 대시보드 완성 · **GCP 결제 해결** | 🤖 👤 |
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
├── api/           dashboard.py(+SSE) · x402.py
├── agents/        hq/{agent,prompt}.py · store/{agent,prompt}.py
│                  utils.py(공통 계산) · runner.py(실행·재시도) · prompt_kit.py
├── core/          protocol.py(x402 메시지) · fixtures.py
├── db/            store.py(파사드) → local_store.py | postgres_store.py
├── llm/           mock.py (규칙 기반 플래너)
└── solana/        payments.py (TS 결제 서비스 HTTP 클라이언트)

frontend/          빌드 없는 정적 대시보드 (FastAPI가 /assets로 서빙)
payments/          TypeScript — Solana USDC 전송·검증 (Solana SDK가 JS라서 분리)
```

### 지켜야 할 규칙

- 환경변수는 `config.py`에서만. 다른 모듈에서 `os.getenv` 직접 호출 금지.
- 저장소 접근은 `app.db.store` 파사드로만. local/postgres를 갈아끼운다.
- 프롬프트는 각 에이전트의 `prompt.py`에만. ROLE/TASK/POLICY/OUTPUT 네 섹션 고정.
  프롬프트에 적는 도구 이름은 실제 함수명과 일치해야 한다 (테스트가 검사).
- 에이전트 도구는 부수효과만. 순수 계산은 `agents/utils.py`로.
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

**conda Postgres에는 zoneinfo가 없다.** 시스템 타임존(KST-9)을 못 읽어서 UTC로 고정해뒀다.

**Solana validator가 8000번 포트를 쓴다.** FastAPI는 8080을 쓰는 이유.

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
| [briefing.html](briefing.html) | 전체 브리핑 (사람이 읽는 학습용) |
| [architecture.html](architecture.html) | 아키텍처 시각화 |
| [wbs.md](wbs.md) · [wbs.html](wbs.html) | 남은 기간 작업 분해, 담당·의존성·리스크 |
| [checklist.md](checklist.md) | 제출 전 체크리스트 |
