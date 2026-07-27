"""프롬프트 로더.

각 에이전트 폴더의 `prompts/*.md`를 읽어 시스템 프롬프트로 조립한다.
프롬프트는 코드가 아니라 문서다 — 편집은 md 파일에서 하고, 여기서는 조립만 한다.

파일 규칙 (에이전트마다 동일):
  role.md    누구인가 — 정체성과 입장
  task.md    무엇을 하는가 — 판단 절차
  policy.md  무엇을 지키는가 — 한도·승인·거절 조건. **DB의 사용자 정책이 여기로 주입된다**
  output.md  어떻게 보고하는가

policy.md의 `{auto_pay_limit_usdc}` 같은 자리표시자는 DB에서 읽은 정책 값으로 치환한다.
따라서 md에는 **범용 규칙만** 두고, 개인별 수치는 DB에 둔다.
"""

from functools import lru_cache
from pathlib import Path

SECTIONS = ("role", "task", "policy", "output")
_AGENTS_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def _read(agent: str, section: str) -> str:
    path = _AGENTS_DIR / agent / "prompts" / f"{section}.md"
    if not path.exists():
        raise FileNotFoundError(f"프롬프트 파일 없음: {path}")
    return path.read_text().strip()


def load(agent: str, section: str, **values) -> str:
    """섹션 하나를 읽어 자리표시자를 채운다."""
    text = _read(agent, section)
    if not values:
        return text
    try:
        return text.format(**values)
    except KeyError as exc:
        raise KeyError(f"{agent}/prompts/{section}.md 의 자리표시자 {exc}에 넣을 값이 없습니다") from exc


def system(agent: str, **values) -> str:
    """네 섹션을 태그로 감싸 하나의 시스템 프롬프트로 조립한다."""
    parts = [f"[{name.upper()}]\n{load(agent, name, **values)}" for name in SECTIONS]
    return "\n\n".join(parts)


def placeholders(agent: str, section: str) -> set[str]:
    """md가 요구하는 자리표시자 이름들 — 테스트가 정책 키와 대조한다."""
    import string

    text = _read(agent, section)
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def reload_cache() -> None:
    """md를 고친 뒤 서버 재시작 없이 반영할 때."""
    _read.cache_clear()
