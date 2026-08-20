"""어시스턴트의 조회 범위 — 누가 묻는지에 따라 도구가 보는 데이터를 좁힌다.

owner를 도구 **인자**로 두면 LLM이 임의 값을 채워 남의 지점을 열 수 있다
(도구 시그니처는 모델에게 그대로 노출된다). 그래서 요청 단위 컨텍스트로 주입하고
도구는 그것만 읽는다 — 모델이 건드릴 수 없는 자리에 둔다.

역할 판정: 'hq'·'admin'은 본사, 'store-'로 시작하면 그 지점. 알 수 없는 값은
지점으로 본다 — 넓게 여는 쪽으로 실수하지 않는다.
"""

from contextvars import ContextVar, Token

# 기본값은 본사가 아니다 — 컨텍스트 주입이 빠지면 아무것도 안 보이는 쪽으로 실패해야 한다.
_OWNER: ContextVar[str] = ContextVar("assistant_owner", default="unbound")

HQ_ROLES = ("hq", "admin")

HQ_ONLY = {"error": "본사 정산팀만 볼 수 있어요. 이 창에서는 우리 지점 것만 조회됩니다."}
OTHER_STORE = {"error": "다른 지점 정보는 볼 수 없어요. 우리 지점 것만 조회됩니다."}
HQ_ACTION = {"error": "승인·반려는 본사 정산팀 권한이에요. 본사에 요청이 올라가 있습니다."}


def bind(owner: str | None) -> Token:
    return _OWNER.set((owner or "unbound").strip() or "unbound")


def reset(token: Token) -> None:
    _OWNER.reset(token)


def owner() -> str:
    return _OWNER.get()


def is_hq() -> bool:
    return owner() in HQ_ROLES


def store_id() -> str | None:
    """지점 창구면 그 지점 ID, 본사면 None."""
    return None if is_hq() else owner()


def mine(doc: dict) -> bool:
    """이 문서가 지금 창구의 것인지. 본사는 전부 자기 것이다."""
    sid = store_id()
    if sid is None:
        return True
    return doc.get("store_id") == sid


def mine_trade(trade: dict) -> bool:
    """직거래는 사는 쪽·파는 쪽 양쪽이 당사자다."""
    sid = store_id()
    if sid is None:
        return True
    return sid in (trade.get("buyer_id"), trade.get("seller_id"))
