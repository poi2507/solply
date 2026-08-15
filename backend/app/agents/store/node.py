"""가맹점 그래프의 노드.

노드 하나 = 판단 또는 실행 한 단계. 상태를 읽고 부분 갱신본을 돌려준다.
LLM이 필요한 노드는 `llm.judge()`를 호출하고, 나머지는 도구를 그대로 부른다.

노드를 이렇게 쪼갠 이유: 어디서 무슨 판단이 일어나는지가 그래프에 그대로 드러나야
발표에서 아키텍처를 설명할 수 있고, 실패한 단계만 재실행할 수 있다.
"""

from app.agents import utils
from app.agents.store import tools
from app.agents.store.state import StoreState
from app.core import policy as policy_mod
from app.llm import judge


def load_context(state: StoreState) -> dict:
    """정책을 DB에서 읽고 처리 대상(청구서 또는 직거래 건)을 집는다. 모든 경로의 시작점."""
    store_id = state["store_id"]
    base = {"policy": policy_mod.get(store_id).as_prompt_values()}

    if state.get("intent", "").startswith(("restock.", "p2p.")):
        if not state.get("trade_id"):
            return base  # 재고 점검(restock.check)은 대상 문서 없이 시작한다
        trade = utils.get_trade(state["trade_id"])
        if not trade:
            return {**base, "outcome": "noop", "messages": [f"직거래 건을 찾을 수 없습니다: {state['trade_id']}"]}
        return {**base, "trade": trade}

    invoice = utils.get_invoice(state["invoice_id"], store_id=store_id) if state.get("invoice_id") else None
    if not invoice:
        return {
            **base,
            "outcome": "noop",
            "messages": [f"처리할 청구서가 없습니다: {state.get('invoice_id')}"],
        }
    return {**base, "invoice": invoice}


def verify_delivery(state: StoreState) -> dict:
    """청구 품목을 발주 내역·검수 기록과 대조한다.

    두 가지 이상을 구분한다: 발주한 품목의 수량 불일치는 협상(차감 제안) 대상이고,
    **발주한 적 없는 품목의 청구는 거부** 대상이다 — 깎아줄 문제가 아니라 내면 안 되는 돈이다.
    """
    store_id = state["store_id"]
    result = tools.verify_delivery(store_id, state["invoice_id"])

    suspects = utils.unordered_items(utils.store_orders(store_id), state["invoice"]["items"])
    if suspects:
        names = ", ".join(f"{i['name']} ×{i['qty']}" for i in suspects)
        total = round(sum(i["qty"] * i["unit_price_usdc"] for i in suspects), 2)
        return {
            "verification": {**result, "suspect_items": suspects},
            "messages": [f"발주 내역에 없는 품목이 청구됐습니다: {names} ({total} USDC)"],
            "reasoning": [f"발주 SKU 목록 대조 — {names}는 발주 기록이 없다"],
        }

    if result.get("match"):
        return {"verification": result, "messages": ["검수 대조 결과 일치합니다."]}

    total = utils.total_over_billed(result["discrepancies"])
    detail = utils.describe_discrepancies(result["discrepancies"])
    return {
        "verification": result,
        "messages": [f"검수 불일치 발견: {detail} (과청구 {total} USDC)"],
        "reasoning": [f"자체 검수 기록 대조 — {detail}"],
    }


def propose_adjustment(state: StoreState) -> dict:
    """불일치분 차감을 제안하고 결제를 보류한다."""
    discrepancies = state["verification"]["discrepancies"]
    total = utils.total_over_billed(discrepancies)
    reason = f"검수 불일치: {utils.describe_discrepancies(discrepancies)}"
    proposal = tools.propose_adjustment(state["store_id"], state["invoice_id"], total, reason)
    return {
        "proposal": proposal,
        "outcome": "negotiating",
        "messages": [f"본사에 {total} USDC 차감을 제안했습니다. 조정 전까지 결제를 보류합니다."],
    }


def request_terms(state: StoreState) -> dict:
    """본사에 정산을 요청한다 — 402 챌린지의 accepts[]가 협상 테이블이다."""
    result = tools.request_settlement_terms(state["store_id"], state["invoice_id"])
    if result.get("error"):
        return {"outcome": "noop", "messages": [result["error"]]}
    if result.get("already_settled"):
        return {"outcome": "noop", "messages": ["이미 정산이 끝난 청구서입니다."]}

    accepts = result["accepts"]
    labels = " · ".join(a.get("extra", {}).get("label", "?") for a in accepts)
    return {
        "x402_terms": accepts,
        "messages": [f"본사에 정산을 요청하니 402(Payment Required)와 결제 조건 {len(accepts)}개를 받았습니다: {labels}"],
    }


def assess_cashflow(state: StoreState) -> dict:
    """잔액·정책 한도·예상 입금으로 지불 여력을 본다."""
    cash = tools.assess_cashflow(state["store_id"], state["invoice_id"])
    return {"cashflow": cash}


def execute_payment(state: StoreState) -> dict:
    """402 조건 중 즉시 납부를 선택해 결제하고, 서명 제출로 정산 확정까지 받는다."""
    term = utils.pick_term(state.get("x402_terms", []), "immediate")
    result = tools.execute_payment(
        state["store_id"], state["invoice_id"], term=term,
        human_approved=state.get("intent") == "invoice.pay_approved",
    )
    if result.get("status") == "needs_human_approval":
        return {
            "outcome": "needs_human",
            "messages": [result["reason"]],
            "reasoning": ["정책 상한 초과로 자동 결제를 중단했습니다."],
        }
    if result.get("error"):
        return {"outcome": "noop", "messages": [result["error"]], "tx_signature": result.get("signature", "")}

    if result.get("settled"):
        return {
            "outcome": "paid",
            "tx_signature": result["signature"],
            "messages": [
                (
                    f"즉시 납부 조건으로 {result['amount']} USDC를 결제하고 서명을 제출했습니다. "
                    f"본사가 온체인 대조 후 정산을 확정했습니다. tx {result['signature'][:16]}…"
                )
            ],
            "reasoning": ["402 조건 중 즉시 납부 선택 — 잔액·상한·하한 모두 충족"],
        }
    return {
        "outcome": "paid",
        "tx_signature": result["signature"],
        "messages": [f"{result['amount']} USDC를 결제했습니다. tx {result['signature'][:16]}…"],
    }


def escalate(state: StoreState) -> dict:
    """자동결제 상한을 넘는 청구 — 능력이 아니라 권한의 문제라 사람에게 넘긴다."""
    cash = state["cashflow"]
    reason = (
        f"청구액 {cash['invoice_amount_usdc']} USDC가 자동결제 상한 "
        f"{cash['auto_pay_limit_usdc']} USDC를 초과합니다."
    )
    tools.request_approval(state["store_id"], state["invoice_id"], reason)
    return {
        "outcome": "needs_human",
        "messages": [f"{reason} 결제를 보류하고 담당자 승인을 요청했습니다."],
        "reasoning": ["점주가 정한 상한을 넘는 금액이라 에이전트가 단독으로 결정하지 않았습니다."],
    }


def propose_deferral(state: StoreState) -> dict:
    """잔액이 모자라면 402 조건 중 유예를 선택하고, 예상 입금 일정을 근거로 제안한다."""
    cash = state["cashflow"]
    forecast = cash.get("pos_forecast", {})
    when = forecast.get("inflow_date", "다음 정산일")
    # 못 내는 이유는 둘이다: 잔액 자체가 모자라거나, 내고 나면 하한이 깨지거나.
    if not cash.get("sufficient", True):
        shortage = (
            f"현재 잔액 {cash['wallet_usdc']} USDC로 청구액 "
            f"{cash['invoice_amount_usdc']} USDC 부족."
        )
    else:
        shortage = (
            f"청구액 {cash['invoice_amount_usdc']} USDC를 내면 잔액이 "
            f"최소 보유 기준 {cash.get('min_reserve_usdc', 0)} USDC 아래로 내려갑니다."
        )
    reason = f"{shortage} {forecast.get('note', '')}".strip()
    proposal = tools.propose_deferral(state["store_id"], state["invoice_id"], when, reason)

    deferred = utils.pick_term(state.get("x402_terms", []), "deferred")
    picked = "402 조건 중 '납부 유예(본사 심사 필요)'를 선택했습니다. " if deferred else ""
    return {
        "proposal": proposal,
        "outcome": "negotiating",
        "messages": [f"{picked}{when}에 납부하겠다고 유예를 제안했습니다. 사유: {reason}"],
        "reasoning": [reason],
    }


def refuse(state: StoreState) -> dict:
    """이상 청구를 거부하고 사람에게 넘긴다."""
    suspects = state.get("verification", {}).get("suspect_items", [])
    if suspects:
        names = ", ".join(f"{i['name']} ×{i['qty']}" for i in suspects)
        reason = f"발주 내역에 없는 품목 청구: {names}"
    else:
        reason = state.get("payload", {}).get("refuse_reason") or "발주 내역에 없는 청구입니다."
    tools.refuse_payment(state["store_id"], state["invoice_id"], reason)
    return {
        "outcome": "refused",
        "messages": [f"결제를 거부하고 담당자에게 넘겼습니다. 사유: {reason}"],
        "reasoning": ["에이전트는 근거 없는 돈을 쓰지 않는다 — 거부 후 사람 확인"],
    }


# ── 지점 간 직거래 (P2P) ─────────────────────────────────────────────

def check_stock(state: StoreState) -> dict:
    """(구매측) 재고를 점검한다. 안전재고 미달이 조달의 트리거다."""
    result = tools.check_inventory(state["store_id"])
    shortages = result["shortages"]
    if not shortages:
        return {"outcome": "noop", "messages": ["재고가 전 품목 안전재고 위입니다 — 조달 불필요."]}

    s = shortages[0]
    return {
        "inventory": result["inventory"],
        "shortage": s,
        "messages": [
            (
                f"재고 점검: {s['name']}이 {s['qty']}개로 안전재고({s['safety']}개) 미달 — "
                f"{s['need']}개 조달이 필요합니다."
            )
        ],
    }


def find_supply(state: StoreState) -> dict:
    """(구매측) 본사 발주와 지점 잉여를 비교해 조달 경로를 고른다.

    비교에 앞서 외부 시세를 pay.sh(x402)로 구매한다 — 판단 재료도 공짜가 아니고,
    데이터 구매 결제가 영수증과 함께 증빙으로 남는다.
    """
    s = state["shortage"]
    quote = tools.fetch_market_quote(state["store_id"], s["sku"])
    quote_msgs = [f"외부 시세를 x402로 구매했습니다 — {quote['summary']}."] if quote else []
    quote_reason = (
        ["시세는 무료 크롤링이 아니라 pay.sh 유료 API에서 구매한 판단 재료 — 결제 영수증이 증빙으로 남는다"]
        if quote else []
    )

    result = tools.find_peer_supply(state["store_id"], s["sku"], s["need"])
    hq_terms = result["hq_reorder"]
    hq_line = (
        f"본사 발주는 리드타임 {hq_terms.get('lead_time', '?')}, 최소 {hq_terms.get('min_qty', '?')}개"
        if hq_terms else "본사 발주 조건 미확인"
    )
    if not result["peers"]:
        return {
            "outcome": "noop",
            "messages": [*quote_msgs, f"잉여 지점이 없습니다. {hq_line} — 본사 발주로 진행합니다."],
            "reasoning": quote_reason,
            **({"market_quote": quote} if quote else {}),
        }

    best = max(result["peers"], key=lambda p: p["surplus"])
    # 잉여가 있다고 늘 직거래는 아니다 — 리드타임·최소 발주량·시세를 놓고 에이전트가 고른다
    verdict = judge.store_decide(
        "supply_route",
        {
            "품목": s.get("name", s["sku"]),
            "need_qty": s["need"],
            "peer_surplus_qty": best["surplus"],
            "이웃_지점": best["name"],
            "hq_min_order_qty": hq_terms.get("min_qty", 0),
            "본사_리드타임": hq_terms.get("lead_time", "미확인"),
            "본사_공급가_usdc": hq_terms.get("unit_price_usdc", 0),
            "구매한_시세": quote["summary"] if quote else "없음",
        },
        state.get("policy", {}),
    )
    if verdict["decision"] != "p2p":
        return {
            "outcome": "noop",
            "messages": [
                *quote_msgs,
                (f"조달 비교 — {hq_line}. {best['name']} 잉여 {best['surplus']}개. "
                 f"본사 발주로 진행합니다."),
            ],
            "reasoning": [*quote_reason, verdict["reasoning"]],
            **({"market_quote": quote} if quote else {}),
        }
    return {
        "supply": {**best, "unit_price_usdc": hq_terms.get("unit_price_usdc", 0)},
        "messages": [
            *quote_msgs,
            f"조달 비교 — {hq_line}. {best['name']}에 잉여 {best['surplus']}개, 오늘 인수 가능.",
        ],
        "reasoning": [*quote_reason, verdict["reasoning"]],
        **({"market_quote": quote} if quote else {}),
    }


def propose_trade(state: StoreState) -> dict:
    """(구매측) 잉여 지점에 직거래를 제안한다. 가격 = 본사 공급가에 시세 추세 반영.

    구매한 시세가 제안 문서(basis)와 가격 양쪽에 남는다 — 돈 주고 산 데이터가
    기록이 아니라 판단을 바꾼다. 반영 폭은 utils.fair_price의 밴드가 지킨다.
    """
    s, sup = state["shortage"], state["supply"]
    quote = state.get("market_quote")
    unit, price_note = utils.fair_price(sup["unit_price_usdc"], quote)
    price = round(s["need"] * unit, 2)
    basis = f"구매한 외부 시세: {quote['summary']} — pay.sh(x402) 결제" if quote else None
    trade = tools.propose_p2p_trade(
        state["store_id"], sup["store_id"], s["sku"], s["name"], s["need"], price,
        basis=basis,
    )
    priced = "시세 반영 단가" if price_note else "본사 공급가 기준"
    return {
        "trade": trade,
        "trade_id": trade["id"],
        "outcome": "negotiating",
        "messages": [
            (
                f"{sup['name']}에 직거래를 제안했습니다: {s['name']} {s['need']}개, "
                f"{price} USDC ({priced}), 오늘 픽업."
            )
        ],
        "reasoning": [price_note] if price_note else [],
    }


def respond_counter(state: StoreState) -> dict:
    """(협상 라운드 2) 본사의 분할 역제안에 잔액·예상 입금을 근거로 응답한다.

    다양성은 난수가 아니라 입력에서 온다 — 같은 역제안이라도 지갑 사정에 따라
    수락 / 선납 수정안 / 결렬로 갈린다. 지점 응답은 규칙 판단이다 — 심사 쪽
    LLM 호출(본사 2회)만으로 협상 예산을 지키기 위해서다 (8/11 Vertex 429 실측).
    """
    terms = state.get("payload", {}).get("terms", {})
    per = float(terms.get("per_usdc") or 0)
    cash = tools.assess_cashflow(state["store_id"], state["invoice_id"])
    wallet = cash["wallet_usdc"]
    afford = round(max(0.0, wallet - cash.get("min_reserve_usdc", 0)), 2)
    forecast = cash.get("pos_forecast", {}).get("note", "")

    # 선택은 에이전트가, 금액은 코드가 — 환각이 잔액을 넘는 선납을 약속하면 그대로 돈이 나간다
    verdict = judge.store_decide(
        "counter_response",
        {
            "청구액_usdc": cash.get("invoice_amount_usdc"),
            "per_usdc": per,
            "분할_회차": terms.get("parts"),
            "지갑_잔액_usdc": wallet,
            "affordable_usdc": afford,
            "예상_입금": forecast or "미확인",
        },
        state.get("policy", {}),
    )
    decision = verdict["decision"]
    resp_terms = {"first_usdc": afford} if decision == "counter" else {}
    reason = verdict["reasoning"]
    if decision == "counter":
        reason = f"{reason} 지금 가능한 {afford} USDC를 선납하고 잔여는 예정일에 냅니다."

    tools.respond_counter_offer(state["store_id"], state["invoice_id"], decision, resp_terms, reason)
    return {
        "proposal": {"decision": decision, "terms": resp_terms},
        "outcome": "refused" if decision == "reject" else "negotiating",
        "messages": [reason],
        "reasoning": [reason],
    }


def respond_trade(state: StoreState) -> dict:
    """(판매측) 자기 재고와 안전재고를 확인하고 제안에 응답한다."""
    trade = state["trade"]
    store_id = state["store_id"]
    pol = policy_mod.get(store_id)
    inventory = tools.check_inventory(store_id)["inventory"]
    sellable = utils.sellable_surplus(inventory, trade["sku"], pol.safety_stock_multiplier)
    entry = inventory.get(trade["sku"], {})

    if sellable >= trade["qty"]:
        decision = "accept"
        reasoning = (
            f"보유 {entry.get('qty', 0)}개 중 안전재고 {entry.get('safety', 0)}개를 지키고도 "
            f"{sellable}개 판매 가능 — 폐기 위험 재고를 현금화합니다."
        )
    else:
        decision = "reject"
        reasoning = f"판매 가능 잉여가 {sellable}개뿐이라 요청 수량 {trade['qty']}개를 내주면 안전재고가 깨집니다."

    result = tools.respond_p2p_trade(store_id, trade["id"], decision, reasoning)
    if result.get("error"):
        return {"outcome": "noop", "messages": [result["error"]]}
    return {
        "trade": result,
        "outcome": "negotiating",
        "messages": [("제안을 수락했습니다. " if decision == "accept" else "제안을 거절했습니다. ") + reasoning],
        "reasoning": [reasoning],
    }


def pay_trade(state: StoreState) -> dict:
    """(구매측) 본사 승인이 확인된 직거래 대금을 x402 왕복으로 결제한다."""
    result = tools.pay_p2p_trade(state["store_id"], state["trade_id"])
    if result.get("status") == "needs_human_approval":
        return {"outcome": "needs_human", "messages": [result["reason"]]}
    if result.get("error"):
        return {"outcome": "noop", "messages": [result["error"]]}
    return {
        "outcome": "paid",
        "tx_signature": result["signature"],
        "messages": [
            (
                f"직거래 대금 {result['amount']} USDC를 본사 에스크로에 예치하고 서명을 제출했습니다. "
                f"인도가 확인되면 본사가 판매 지점에 지급합니다. tx {result['signature'][:16]}…"
            )
        ],
        "reasoning": ["본사 승인 확인 후 결제 — 승인 없는 직거래는 결제하지 않는다"],
    }


def report(state: StoreState) -> dict:
    """지금까지의 판단을 사람이 읽는 한 문단으로 정리한다 (LLM).

    noop으로 끝난 판은 요약을 만들지 않는다 — 판단 없는 판에 LLM 호출을 쓰지
    않는 것이 협상 다회 왕복의 호출 예산이다 (8/11 라이브: 틱 한 번에 Vertex 429).
    """
    if not state.get("messages") or state.get("outcome") == "noop":
        return {}
    summary = judge.narrate(
        agent="store",
        prompt_values=state.get("policy", {}),
        facts=state["messages"],
        reasoning=state.get("reasoning", []),
    )
    return {"messages": [summary] if summary else []}


# ── 분기 조건 ────────────────────────────────────────────────────────

_P2P_ROUTE = {
    "restock.check": "check_stock",   # 구매측: 재고 점검 → 조달
    "p2p.respond": "respond_trade",   # 판매측: 제안 응답
    "p2p.pay": "pay_trade",           # 구매측: 승인된 거래 결제
}


def route_after_context(state: StoreState) -> str:
    """청구서가 없으면 끝, 재발행분·예약 실행분이면 검수를 건너뛰고 바로 정산 요청."""
    if state.get("outcome") == "noop":
        return "end"
    intent = state.get("intent", "")
    if intent in _P2P_ROUTE:
        return _P2P_ROUTE[intent]
    if intent == "proposal.counter":  # 본사 역제안에 대한 재응수 (협상 라운드 2)
        return "respond_counter"
    if intent in (
        "invoice.pay_adjusted",     # 차감 합의로 재발행된 청구서
        "invoice.pay_scheduled",    # 예약일이 온 청구서
        "invoice.pay_installment",  # 분할 합의의 1회차
        "invoice.pay_approved",     # 사람이 승인한 한도 초과 건
    ):
        return "request_terms"
    if state.get("payload", {}).get("suspect"):
        return "refuse"
    return "verify"


def route_after_stock(state: StoreState) -> str:
    return "report" if state.get("outcome") == "noop" else "find_supply"


def route_after_supply(state: StoreState) -> str:
    return "report" if state.get("outcome") == "noop" else "propose_trade"


def route_after_verify(state: StoreState) -> str:
    """미발주 품목이면 거부, 수량 불일치면 협상, 일치할 때만 정산 테이블에 앉는다."""
    if state["verification"].get("suspect_items"):
        return "refuse"
    return "request_terms" if state["verification"]["match"] else "propose_adjustment"


def route_after_terms(state: StoreState) -> str:
    return "report" if state.get("outcome") == "noop" else "cashflow"


def route_after_cashflow(state: StoreState) -> str:
    """상한(권한)을 먼저 보고, 그 다음 잔액과 하한(능력)을 본다.

    순서가 중요하다. 상한 초과는 "이 금액은 애초에 에이전트가 정할 문제가 아니다"라는
    권한의 문제라, 잔액이 넉넉하든 아니든 사람에게 간다.
    사람이 이미 승인한 건(pay_approved)은 권한 문제가 해소된 상태라 바로 결제로 간다.
    """
    if state.get("intent") == "invoice.pay_approved":
        return "pay"
    cash = state["cashflow"]
    if not cash.get("within_auto_limit", True):
        return "escalate"
    if not cash.get("sufficient") or not cash.get("keeps_reserve", True):
        return "propose_deferral"
    return "pay"
