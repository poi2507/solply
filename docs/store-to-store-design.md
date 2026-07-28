# 가맹점 간 직거래 (Store-to-Store) — 시나리오 E 구현 설계

> 2026-07-27 작성 (사용자 아이디어). **2026-07-28 구현 완료** — 이 문서는 ADK 구조 기준이라
> 실제 구현은 LangGraph 구조(그래프 노드 + tools)로 옮겨졌다. 현황은 [wbs.md](wbs.md) Phase 2.5.
> 배경 요약은 [product-design.md](product-design.md) §2.

## 한 줄 요약

지금은 본사↔가맹점 세로 소통뿐이다. **가맹점 에이전트끼리 가로로 협상**을 추가한다 —
A지점은 재고가 남고 B지점은 재고가 바닥일 때, B가 본사에 발주하는 대신
**A와 직접 협상해 잉여 재고를 넘겨받고, 대금은 B → A로 온체인 USDC 결제**한다.

## 왜 하나

- **트랙 C 정면 부합**: "Multi-Agent Commerce — 에이전트 간 A2A/A2B 협상·주문·결제". 기존 시나리오(A/B/C)는 트랙 A·B만 커버한다. 이게 들어가면 세 트랙을 한 프로덕트로 관통한다.
- **차별화 논거 강화**: "협상이 우리 훅"인데, 지금까지는 본사-가맹점 협상뿐. 가맹점-가맹점 협상이 추가되면 멀티에이전트 서사가 완성된다.
- **비즈니스 가치**: A는 폐기 손실 감소, B는 긴급 발주 리드타임 단축, 본사는 물류비 절감.
- **구현이 싸다**: 가맹점 에이전트는 같은 코드에 지갑·정책만 다르다. `payments.pay(store_id, to_address, amount, memo)`는 이미 임의 수취인을 받으므로 B→A 결제에 그대로 쓴다. 결제 레일 전부 재사용.

## 시나리오 E (데모 대본)

> 데이터 전제: A지점은 냉장 닭(CHK-10) 재고 잉여, B지점은 재고 소진 + 주말 매출 피크 임박.

1. **B지점**: 재고 점검 → CHK-10이 안전재고 아래 → 본사 긴급 발주 견적 확인 (리드타임 D+2, 배송비 포함)
2. **B지점 → 지점망**: 인근 지점 잉여 조회 → A지점에 CHK-10 6개 잉여 발견
3. **B지점 → A지점**: 직거래 제안 (수량 4, 본사 공급가 기준 10 USDC, 오늘 픽업)
4. **A지점**: 자기 재고·판매 예측 확인 → 안전재고를 지키는 범위에서 수락
5. **본사**: 거래 심사 — 위생·품질 정책, 두 지점 신용 확인 → **승인** (여기가 "자율성 + 통제"의 P2P 확장)
6. **B지점 → A지점**: 온체인 USDC 결제 (memo에 거래 ID)
7. **A지점**: 트랜잭션 검증 → 재고 이전 확정
8. **본사**: 거래를 본사 장부에 기록 ("같은 장부" 논거 유지) → 대시보드에 P2P 거래 표시

핵심 컷: **"본사를 거치지 않은 거래인데도, 협상·통제·증빙은 전부 남는다."**

## 구현 작업 분해

### 1. 데이터 — `backend/data/fixtures.json`

`inventory` 섹션 추가. 시나리오는 코드가 아니라 데이터로 만든다(기존 원칙).

```json
"inventory": {
  "store-a": { "CHK-10": { "qty": 10, "safety": 4, "note": "지난주 과발주로 잉여" } },
  "store-b": { "CHK-10": { "qty": 0,  "safety": 4, "note": "주말 피크 임박, 소진" } },
  "store-c": { "CHK-10": { "qty": 5,  "safety": 4 } }
},
"hq_reorder": {
  "CHK-10": { "unit_price_usdc": 2.5, "lead_time": "D+2", "min_qty": 10 }
}
```

- A의 잉여 = qty 10 − safety 4 = 6개. B의 필요 = 4개 → A가 안전재고를 지키며 팔 수 있는 수량 안.
- `hq_reorder`는 "본사 발주는 D+2에 최소 10개" — B가 직거래를 선택하는 **판단 근거**가 된다 (긴급성 + 소량).
- 기존 `deliveries`/`receiving_logs`는 건드리지 않는다 (`tests/test_core.py`가 지킨다).

### 2. 가맹점 도구 — `backend/app/agents/store/agent.py` `make_tools()`에 추가

기존 7개 도구 패턴(부수효과는 도구에, 순수 계산은 `agents/utils.py`) 그대로.

| 도구 | 하는 일 |
|---|---|
| `check_inventory()` | 자기 지점 재고·안전재고 조회 (fixtures + db 반영분) |
| `find_peer_supply(sku, qty)` | 다른 지점들의 잉여(qty − safety) 조회, 본사 발주 조건(`hq_reorder`)과 비교 재료 반환 |
| `propose_p2p_trade(seller_id, sku, qty, price_usdc)` | 직거래 제안 생성 → db `p2p_trades`에 `proposed`로 기록, `p2p.proposed` 이벤트 |
| `respond_p2p_trade(trade_id, decision, reasoning)` | (판매측) 자기 재고·안전재고 확인 후 accept/reject → `p2p.responded` 이벤트 |
| `pay_p2p_trade(trade_id)` | (구매측) `payments.pay(내지점, 판매지점주소, 금액, trade_id)` — **`AGENT_SPEND_LIMIT_USDC` 한도 검사 포함** (`execute_payment`과 동일 패턴), `p2p.paid` 이벤트 |
| `confirm_p2p_trade(trade_id, tx_signature)` | (판매측) `payments.verify_tx`로 금액·memo 대조 → 재고 이전 확정, `p2p.confirmed` 이벤트 |

판매지점 주소는 `payments.balance(seller_id)["address"]`로 얻는다 (`execute_payment`가 hq 주소 얻는 방식과 동일).

### 3. 본사 도구 — `backend/app/agents/hq/agent.py`에 추가

| 도구 | 하는 일 |
|---|---|
| `review_p2p_trade(trade_id, decision, reasoning)` | 위생·품질 정책 + 양쪽 지점 신용 확인 → approve/reject 기록, `p2p.reviewed` 이벤트. reject면 거래 중단 |
| `record_p2p_settlement(trade_id)` | 확정된 거래를 본사 장부(정산 이력)에 기록 — "본사도 같은 장부를 본다" 증빙 |

`TOOLS` 리스트에 추가하는 것 잊지 말 것.

### 4. 저장소 — 새 컬렉션 `p2p_trades`

`app.db.store` 파사드(put/get/update/list_docs)가 컬렉션 이름을 받으므로 **스키마 작업 불필요**. 문서 형태:

```json
{
  "id": "P2P-xxxx", "sku": "CHK-10", "qty": 4, "price_usdc": 10.0,
  "buyer_id": "store-b", "seller_id": "store-a",
  "status": "proposed | accepted | approved | paid | confirmed | rejected",
  "tx_sig": null, "reasoning": {}
}
```

### 5. 프롬프트 — `store/prompt.py`, `hq/prompt.py`

- ROLE/TASK/POLICY/OUTPUT 네 섹션 구조 유지 (`prompt_kit.compose`).
- **프롬프트에 적는 도구 이름은 실제 함수명과 일치해야 한다 — 테스트가 검사한다.**
- 가맹점 POLICY에 추가: "재고가 안전재고 아래면 본사 발주 전에 지점 간 직거래를 먼저 검토. 판매 시 안전재고는 지킨다. 거래는 본사 승인 후에만 결제."
- 본사 POLICY에 추가: "P2P 거래는 위생·품질 기준(냉장·유통기한)과 양쪽 신용을 확인해 승인. 승인 없는 거래는 무효."

### 6. mock 플래너 — `backend/app/llm/mock.py`

`store_planner`/`hq_planner`에 시나리오 E 규칙 추가 (재고 부족 감지 → 조회 → 제안 → 수락 → 승인 → 결제 → 확인 순). `make demo-mock`으로 LLM 없이 리허설 가능해야 한다.

### 7. 데모 — `backend/demo.py`

`scenario_e(hq)` 추가, `scenarios` dict에 `"e"` 등록. 기존 시나리오처럼 오케스트레이터가 프롬프트로 상황을 주입:

1. B지점에게: "주말 피크 전 재고를 점검하고 필요하면 조달하세요"
2. A지점에게: "B지점의 직거래 제안이 도착했습니다. 검토하세요" (`latest_event`로 `p2p.proposed` 집어서)
3. 본사에게: "지점 간 직거래 승인 요청입니다. 심사하세요"
4. B지점에게: "승인됐습니다. 결제하세요"
5. A지점에게: "결제 트랜잭션을 검증하고 재고 이전을 확정하세요"

`summary()`에 p2p_trades도 출력 (✅ P2P-xxxx store-b→store-a 10.00 USDC confirmed + tx).

### 8. 대시보드 — `frontend/`

이벤트는 `utils.log`만 하면 SSE로 자동으로 흐른다. 최소: 이벤트 피드에 `p2p.*`가 보이면 됨.
여유 되면: 지점 카드 사이에 P2P 거래 화살표/카드 하나 (B→A 방향 + 금액 + tx 링크).

### 9. 테스트 — `backend/tests/`

- 잉여 계산(qty − safety), 안전재고 침범 거절, 한도 초과 시 `needs_human_approval`
- 본사 미승인 상태에서 `pay_p2p_trade` 호출 시 거부
- 프롬프트-도구 이름 일치 검사에 새 도구들 포함되는지
- fixtures의 `inventory` 데이터가 시나리오 전제(A 잉여 6, B 부족)를 유지하는지 — 기존 test_core 패턴대로

## 설계 가정 (다르게 가고 싶으면 여기만 바꾸면 됨)

| 항목 | 기본값 | 근거 |
|---|---|---|
| 거래 가격 | 본사 공급가 그대로 (CHK-10 = 2.5 USDC/개) | 지점 간 폭리 방지, 심사 설명 단순. 협상은 **수량·시점**에서 일어남 |
| 본사 역할 | **승인 필수** (approve 없으면 결제 불가) | 프랜차이즈 위생·품질 책임 + "자율성+통제" 서사 유지. Q&A 방어 포인트 |
| 물류 | 데모 범위 밖 (B가 픽업 가정, 대본 한 줄) | 5일 안에 만들 수 있는 범위로 |
| x402 | Phase 1 완료 후라면 지점 간 결제도 x402 왕복으로 (A가 402 챌린지 → B가 결제 → PAYMENT-SIGNATURE) | 심사 기준 3 가산. Phase 1 미완이면 직접 결제로 먼저 완성 |
| 신용 반영 | P2P 정시 이행도 신용 이력에 적립 (Phase 2 신용점수 실계산과 연결) | "납부 이력이 곧 신용" 논거가 P2P까지 확장 |

## 완료 기준

- `make demo-mock`에서 시나리오 E 완주: `p2p.proposed → p2p.responded → p2p.reviewed → p2p.paid → p2p.confirmed` 이벤트가 순서대로 찍힌다
- **B→A 온체인 USDC 트랜잭션**이 실제 발생하고 memo에 거래 ID가 들어간다
- 본사 미승인이면 결제가 막힌다 (테스트로 증명)
- `make test` 전체 통과

## 일정 편성 제안

Phase 1(x402 연결)과 독립적이라 병행 가능하지만, **Phase 2(신용 실계산·거부·예약) 완료 후 착수 추천** — 기존 커밋된 기능이 심사 필수 항목이고, 이건 강력한 가산 항목. 예상 소요 반나절~1일 (mock 플래너와 데모 오케스트레이션이 절반).

데모 영상에 넣을 땐 A(정상) → B(차감 협상) → **E(P2P 직거래)** → C(유예) 순서 추천: "본사와 협상" 다음에 "지점끼리 협상"이 나오면 스토리가 고조된다.
