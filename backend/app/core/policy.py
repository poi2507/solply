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

    kind: str = "store"

    def as_prompt_values(self) -> dict[str, Any]:
        return {
            "store_id": self.owner_id,
            "auto_pay_limit_usdc": _num(self.auto_pay_limit_usdc),
            "min_reserve_usdc": _num(self.min_reserve_usdc),
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

    merged = {**asdict(current), **{k: patch[k] for k in patch}}
    updated = _coerce(merged)
    _validate(updated)
    return store.put(COLLECTION, owner_id, asdict(updated))


def _validate(policy: StorePolicy | HQPolicy) -> None:
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


def describe(owner_id: str) -> list[dict[str, Any]]:
    """프론트 설정 화면이 그대로 렌더할 수 있는 항목 정의."""
    policy = get(owner_id)
    if isinstance(policy, StorePolicy):
        spec = [
            ("auto_pay_limit_usdc", "자동결제 상한", "이 금액까지는 사람 승인 없이 결제합니다", "USDC", 1, 1000),
            ("min_reserve_usdc", "최소 보유 잔액", "결제 후 이 아래로 내려가면 결제하지 않습니다", "USDC", 0, 1000),
            ("defer_request_threshold_pct", "유예 제안 기준", "잔액이 부족할 때 유예를 제안할 비율", "%", 0, 100),
            ("safety_stock_multiplier", "안전재고 배수", "지점 간 직거래로 팔 때 남겨둘 재고 배수", "배", 0, 5),
        ]
    else:
        spec = [
            ("min_credit_score", "유예 승인 최소 신용점수", "이 점수 이상이면 유예를 자동 수락합니다", "점", 0, 100),
            ("p2p_min_credit_score", "직거래 참가 신용점수", "지점 간 직거래는 즉시 결제라 유예보다 완만한 기준을 씁니다", "점", 0, 100),
            ("defer_max_pct", "유예 허용 비율", "외상 한도의 몇 %까지 유예를 허용할지", "%", 0, 100),
            ("installment_max", "분할 최대 회차", "몇 회까지 나눠 받을지", "회", 1, 12),
            ("auto_adjust_limit_usdc", "자동 차감 승인 한도", "이 금액을 넘는 차감은 사람이 확인합니다", "USDC", 0, 1000),
        ]
    current = asdict(policy)
    return [
        {"key": k, "label": label, "help": help_, "unit": unit, "min": lo, "max": hi, "value": current[k]}
        for k, label, help_, unit, lo, hi in spec
    ]
