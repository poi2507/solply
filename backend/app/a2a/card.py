"""Agent Card — 에이전트가 자기 능력을 공개하는 표준 명함.

skills는 그래프의 intent 라우팅 테이블과 같은 목록이어야 한다
(store: route_after_context가 받는 intent / hq: _INTENT_ROUTE). 명함에 없는
스킬은 부를 수 없고, 그래프에 없는 스킬을 명함에 적으면 거짓말이다 — 테스트가 대조한다.
"""

from app import config
from app.core import fixtures

PROTOCOL_VERSION = "0.3.0"

# intent → (이름, 한 줄 설명)
STORE_SKILLS = {
    "invoice.handle": ("청구서 처리", "검수 대조 → x402 조건 수신 → 결제 / 유예 제안 / 거부"),
    "invoice.pay_adjusted": ("정정 청구서 납부", "차감 합의로 재발행된 청구서를 검수 없이 납부"),
    "invoice.pay_scheduled": ("예약 납부 실행", "유예 합의된 청구서를 예약일에 납부"),
    "invoice.pay_installment": ("분할 회차 납부", "분할 합의의 회차 청구서를 납부"),
    "invoice.pay_approved": ("승인 건 결제", "사람이 승인한 한도 초과 건을 결제"),
    "proposal.counter": ("역제안 응답", "본사 분할 역제안에 잔액·예상 입금을 근거로 수락/수정안/결렬 응답"),
    "restock.check": ("재고 점검·조달 판단", "안전재고 미달 시 P2P 직거래와 본사 발주를 비교"),
    "p2p.respond": ("직거래 제안 응답", "판매측 — 안전재고를 지키고 팔 수 있는지, 값을 올려 되제안할지 판단"),
    "p2p.pay": ("직거래 대금 결제", "구매측 — 본사 승인 확인 후 x402 왕복 결제"),
    "p2p.price": ("가격 역제안 응답", "구매측 — 판매측이 올린 값에 오늘 인수 vs 본사 발주를 판단"),
    "p2p.consider": ("중개 제안 응답", "구매측 — 본사가 중개한 부분 잉여 직거래에 동의/거절"),
    "order.adjust": ("발주 축소 제안 응답", "본사의 수량 축소 제안에 자기 판매 시계열로 수용/고수 판단"),
}
HQ_SKILLS = {
    "invoice.issue": ("청구서 발행", "납품 완료 → 청구서 발행"),
    "proposal.adjustment": ("차감 제안 심사", "납품 로그로 사실을 재검증한 뒤 수락/거절"),
    "proposal.deferral": ("유예 제안 심사", "신용 이력·정책 한도 기준 수락/분할 역제안/거절"),
    "proposal.settle": ("협상 종결", "합의를 분할 청구서로 집행하거나 결렬을 사람 승인 큐로"),
    "payment.verify": ("결제 온체인 대조", "금액·memo·성공 3중 대조 후 정산 확정"),
    "p2p.review": ("직거래 심사", "안전재고·양측 신용·가격 기준 승인/반려"),
    "p2p.record": ("직거래 장부 기록", "온체인 확정(CONFIRMED)된 거래를 본사 장부에 기록"),
    "order.review": ("발주 수량 심사", "지점 주문을 지점·전국 일별 시계열로 읽고 이행/축소를 제안"),
    "p2p.broker": ("직거래 중개", "전 지점 과부족을 보고 부분 잉여 직거래를 주선 — 성사는 양쪽 지점 판단"),
}


def known_agents() -> dict[str, str]:
    """agent_id → 그래프 종류. hq 하나 + fixtures의 지점들."""
    agents = {"hq": "hq"}
    for store_id in fixtures.load()["stores"]:
        agents[store_id] = "store"
    return agents


def build(agent_id: str) -> dict:
    """agent_id의 명함. 알 수 없는 에이전트면 KeyError."""
    kind = known_agents()[agent_id]
    if kind == "hq":
        name, desc, skills = "본사 정산 에이전트", "프랜차이즈 본사 — 청구서 발행·협상 심사·정산 대조", HQ_SKILLS
        base = config.A2A_HQ_URL
    else:
        profile = fixtures.load()["stores"][agent_id]
        name = f"{profile['name']} 에이전트"
        desc = "가맹점 — 검수·지불 판단·협상 제안·지점 간 직거래"
        skills, base = STORE_SKILLS, config.A2A_STORE_URL
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "name": name,
        "description": desc,
        "url": f"{base}/a2a/{agent_id}",
        "preferredTransport": "JSONRPC",
        "version": "1.0.0",
        "capabilities": {"streaming": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {"id": intent, "name": title, "description": detail, "tags": intent.split(".")}
            for intent, (title, detail) in skills.items()
        ],
    }
