"""거래 정책 — 사용자가 프론트에서 설정하고 DB에 저장하는 값.

에이전트의 판단 경계는 코드가 아니라 **점주(또는 본사 담당자)가 정한다.**
프롬프트의 policy.md에는 범용 규칙만 두고, 수치는 전부 여기서 주입한다.

컬렉션: `policies` — 문서 ID는 소유자 ID (store-a, store-b, hq …)
"""

from dataclasses import asdict, dataclass, fields
from typing import Any

from app.db import store

COLLECTION = "policies"


@dataclass
class StorePolicy:
    """가맹점 지불 정책 — 점주가 설정한다."""

    owner_id: str

    # 상한: 이 금액까지는 사람 승인 없이 결제한다
    auto_pay_limit_usdc: float = 10.0
    # 하한: 결제 후 이 잔액 아래로 내려가면 결제하지 않는다 (운영 자금 보호)
    min_reserve_usdc: float = 2.0
    # 협상: 이 비율까지는 유예를 먼저 제안해본다
    defer_request_threshold_pct: float = 100.0
    # P2P: 판매 시 남겨둘 안전재고 배수 (1.0 = 안전재고 그대로)
    safety_stock_multiplier: float = 1.0
    # 이 지점의 사정 — 협상·조달에서 에이전트가 참고하는 서술. 비우면 시드값을 쓴다.
    # 한도는 위 숫자들이 강제하고, 이 글은 그 안에서의 재량에만 영향을 준다.
    persona: str = ""

    kind: str = "store"

    def as_prompt_values(self) -> dict[str, Any]:
        # 사정(persona)은 정책이 아니라 지점 프로필이지만 프롬프트에는 함께 들어간다.
        # 여기서 한 번에 실어야 호출부마다 빠뜨리지 않는다.
        from app.core import fixtures

        profile = fixtures.load()["stores"].get(self.owner_id, {})
        return {
            "store_id": self.owner_id,
            "auto_pay_limit_usdc": _num(self.auto_pay_limit_usdc),
            "min_reserve_usdc": _num(self.min_reserve_usdc),
            # 점주가 화면에서 고친 값이 있으면 그것을, 없으면 시드 프로필을 쓴다
            "persona": (self.persona.strip()
                        or profile.get("persona", "특별한 사정 없이 정책대로 판단한다.")),
        }


@dataclass
class HQPolicy:
    """본사 심사 정책 — 정산 담당자가 설정한다."""

    owner_id: str = "hq"

    # 유예를 자동 수락할 최소 신용점수 (유예 = 여신이라 기준이 높다)
    min_credit_score: int = 85
    # 지점 간 직거래 참가 자격 점수 — 즉시 온체인 결제라 여신이 없어 유예보다 완만하다
    p2p_min_credit_score: int = 75
    # 외상 한도의 몇 %까지 유예 잔액을 허용하는가
    # (주의: 청구액 기준이 아니다 — 엔진은 credit_limit_usdc에 대한 비율로 본다)
    defer_max_pct: float = 20.0
    # 분할 최대 회차
    installment_max: int = 2
    # 이 금액을 넘는 차감 요청은 사람이 본다
    auto_adjust_limit_usdc: float = 4.0
    # 카드매출 정산 때 본사가 공제하는 로열티 비율.
    # 폐쇄 풀(총량 고정)에서 요리 마진(1.35)은 판매마다 매출의 26%(0.35/1.35)를
    # 본사→지점으로 영구 이동시킨다 — 환류가 없으면 본사가 필연적으로 마른다
    # (8/11 라이브: 총량 400 중 본사 5.0까지 고갈, 카드정산 정지). 25%를 원천징수하면
    # 본사 순유출이 매출의 1.25%로 줄고 지점은 소폭 흑자를 유지한다.
    royalty_pct: float = 25.0
    # 데이터 상품(체결가 지수·수요 지수) 판매 단가 — 본사의 세 번째 매출원
    data_price_usdc: float = 0.1

    kind: str = "hq"

    def as_prompt_values(self) -> dict[str, Any]:
        return {
            "min_credit_score": self.min_credit_score,
            "defer_max_pct": _num(self.defer_max_pct),
            "installment_max": self.installment_max,
        }


def _num(value: float) -> str:
    """25.0 → "25" / 12.5 → "12.5" — 프롬프트에 소수점 잔여를 남기지 않는다."""
    return f"{value:g}"


_TYPES = {"store": StorePolicy, "hq": HQPolicy}


def _coerce(doc: dict) -> StorePolicy | HQPolicy:
    cls = _TYPES.get(doc.get("kind", "store"), StorePolicy)
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in doc.items() if k in known})


def get(owner_id: str) -> StorePolicy | HQPolicy:
    """저장된 정책을 읽는다. 없으면 기본값 — 설정 전에도 에이전트는 돌아야 한다."""
    doc = store.get(COLLECTION, owner_id)
    if doc:
        return _coerce(doc)
    return HQPolicy() if owner_id == "hq" else StorePolicy(owner_id=owner_id)


def save(owner_id: str, patch: dict[str, Any]) -> dict:
    """프론트에서 온 부분 갱신을 검증해 저장한다."""
    current = get(owner_id)
    allowed = {f.name for f in fields(current)} - {"owner_id", "kind"}
    unknown = set(patch) - allowed
    if unknown:
        raise ValueError(f"알 수 없는 정책 항목: {', '.join(sorted(unknown))}")

    # 글 필드는 persona뿐 — 숫자 필드에 문자열이 들어오면 저장 전에 거른다.
    # (defer_request_threshold_pct처럼 범위 검증이 없는 필드는 문자열이 그대로
    #  저장돼 이후 산술에서 터진다 — API가 str을 받게 되면서 생긴 구멍)
    for key, value in patch.items():
        if key == "persona":
            if not isinstance(value, str):
                raise ValueError("지점 사정은 글로 적어 주세요")
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key}은(는) 숫자여야 합니다")

    merged = {**asdict(current), **{k: patch[k] for k in patch}}
    updated = _coerce(merged)
    _validate(updated)
    return store.put(COLLECTION, owner_id, asdict(updated))


MAX_PERSONA_CHARS = 400

# 프리셋 — 점주가 긴 글 대신 성향을 고른다. 고른 뒤 자유롭게 고쳐 쓸 수 있고,
# 저장되는 것은 어디까지나 최종 글이다 (프리셋은 입력 도우미일 뿐 별도 상태가 아니다).
PERSONA_PRESETS = [
    {"label": "적극 확장",
     "text": ("매출이 안정적이라 현금 여유가 있다. 결품으로 손님을 놓치는 것을 가장 싫어해 "
              "재고를 넉넉히 잡고 조달에 적극적이다. 감당 가능한 분할 조건이면 협상을 "
              "길게 끌지 않고 받아들인다.")},
    {"label": "균형",
     "text": ("매출 편차가 있어 현금을 아껴 쓰고, 한 번에 큰 금액이 나가는 것을 피한다. "
              "전액보다 일부 선납으로 쪼개는 조건을 선호하고, 이웃 직거래로 단가를 "
              "낮출 기회를 먼저 살핀다.")},
    {"label": "절약 보수",
     "text": ("여유 자금이 얇아 지불 여력을 지키는 것이 최우선이다. 재고는 최소로 가져가고, "
              "무리한 분할을 떠안기보다 유예를 먼저 요청한다. 감당할 수 없으면 결렬을 "
              "감수하고 사람의 판단을 구한다.")},
]


def _validate(policy: StorePolicy | HQPolicy) -> None:
    if isinstance(policy, StorePolicy) and len(policy.persona) > MAX_PERSONA_CHARS:
        raise ValueError(f"지점 사정은 {MAX_PERSONA_CHARS}자 이내로 적어 주세요")
    if isinstance(policy, StorePolicy):
        if policy.auto_pay_limit_usdc <= 0:
            raise ValueError("자동결제 상한은 0보다 커야 합니다")
        if policy.min_reserve_usdc < 0:
            raise ValueError("최소 보유 잔액은 0 이상이어야 합니다")
        if policy.safety_stock_multiplier < 0:
            raise ValueError("안전재고 배수는 0 이상이어야 합니다")
    else:
        if not 0 <= policy.min_credit_score <= 100:
            raise ValueError("신용점수 기준은 0~100 사이여야 합니다")
        if not 0 <= policy.p2p_min_credit_score <= 100:
            raise ValueError("직거래 신용점수 기준은 0~100 사이여야 합니다")
        if not 0 <= policy.defer_max_pct <= 100:
            raise ValueError("유예 허용 비율은 0~100% 사이여야 합니다")
        if policy.installment_max < 1:
            raise ValueError("분할 최대 회차는 1 이상이어야 합니다")
        if not 0 <= policy.royalty_pct <= 50:
            raise ValueError("로열티 비율은 0~50% 사이여야 합니다")
        if policy.data_price_usdc < 0:
            raise ValueError("데이터 판매 단가는 0 이상이어야 합니다")


def describe(owner_id: str) -> list[dict[str, Any]]:
    """프론트 설정 화면이 그대로 렌더할 수 있는 항목 정의."""
    policy = get(owner_id)
    text_spec: list[tuple[str, str, str]] = []
    if isinstance(policy, StorePolicy):
        spec = [
            ("auto_pay_limit_usdc", "자동결제 상한", "이 금액까지는 사람 승인 없이 결제합니다", "USDC", 1, 1000),
            ("min_reserve_usdc", "최소 보유 잔액", "결제 후 이 아래로 내려가면 결제하지 않습니다", "USDC", 0, 1000),
            ("defer_request_threshold_pct", "유예 제안 기준", "잔액이 부족할 때 유예를 제안할 비율", "%", 0, 100),
            ("safety_stock_multiplier", "안전재고 배수", "지점 간 직거래로 팔 때 남겨둘 재고 배수", "배", 0, 5),
        ]
        text_spec += [
            ("persona", "우리 지점 사정",
             ("에이전트가 협상·조달에서 참고합니다. 성향을 고르거나 직접 고쳐 쓰세요 — "
              "같은 조건에도 다르게 판단합니다. 한도는 위 숫자가 강제합니다.")),
        ]
    else:
        spec = [
            ("min_credit_score", "유예 승인 최소 신용점수", "이 점수 이상이면 유예를 자동 수락합니다", "점", 0, 100),
            ("p2p_min_credit_score", "직거래 참가 신용점수", "지점 간 직거래는 즉시 결제라 유예보다 완만한 기준을 씁니다", "점", 0, 100),
            ("defer_max_pct", "유예 허용 비율", "외상 한도의 몇 %까지 유예를 허용할지", "%", 0, 100),
            ("installment_max", "분할 최대 회차", "몇 회까지 나눠 받을지", "회", 1, 12),
            ("auto_adjust_limit_usdc", "자동 차감 승인 한도", "이 금액을 넘는 차감은 사람이 확인합니다", "USDC", 0, 1000),
            ("royalty_pct", "카드정산 로열티", "카드매출 정산 때 공제하는 비율 — 마진으로 새는 본사 유동성을 환류시킵니다", "%", 0, 50),
            ("data_price_usdc", "데이터 판매 단가", "체결가·수요 지수 1건 조회 가격 (x402)", "USDC", 0, 10),
        ]
    current = asdict(policy)
    fields = [
        {"key": k, "label": label, "help": help_, "unit": unit,
         "min": lo, "max": hi, "value": current[k], "type": "number"}
        for k, label, help_, unit, lo, hi in spec
    ]
    fields += [
        {"key": k, "label": label, "help": help_, "type": "text",
         "value": current[k] or policy.as_prompt_values().get(k, ""),
         "maxlength": MAX_PERSONA_CHARS, "presets": PERSONA_PRESETS}
        for k, label, help_ in text_spec
    ]
    return fields
