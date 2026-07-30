"""한국 시간 기준 하루 — 정산은 날짜 단위 업무다.

대시보드는 기본으로 '오늘'만 보여주고 날짜를 옮겨 과거를 본다.
그 하루의 경계를 여기서 한 곳으로 정한다 (UTC로 저장된 시각을 KST 날짜로 묶는다).
"""

from datetime import UTC, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def today() -> str:
    """오늘 날짜 (KST, YYYY-MM-DD)."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def parse(day: str | None) -> str:
    """날짜 문자열을 검증해 돌려준다. 없거나 형식이 틀리면 오늘."""
    if not day:
        return today()
    try:
        datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=KST)
    except ValueError:
        return today()
    return day


def bounds(day: str) -> tuple[datetime, datetime]:
    """그 날 하루의 UTC 구간 [시작, 끝) — KST 자정부터 다음 자정까지."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=KST)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def day_of(moment: str | datetime) -> str:
    """UTC 시각(ISO 문자열 또는 datetime)이 속한 KST 날짜."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(KST).strftime("%Y-%m-%d")


def shift(day: str, days: int) -> str:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=KST) + timedelta(days=days)
    return start.strftime("%Y-%m-%d")
