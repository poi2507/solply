"""프롬프트 작성 규칙.

에이전트 프롬프트는 아래 섹션으로만 구성한다. 각 에이전트 폴더의 `prompt.py`가
이 상수들을 채우고 `compose()`로 조립한다. 섹션을 고정하면 프롬프트를 고칠 때
"어디를 고쳐야 하는가"가 분명해지고, 에이전트끼리 비교하기도 쉽다.

  ROLE    누구인가 — 정체성과 입장(돈을 받는 쪽 / 내는 쪽)
  TASK    무엇을 하는가 — 처리 순서. 번호를 매겨 결정 경로를 명시한다
  POLICY  무엇을 지키는가 — 한도·승인·거절 조건. 자율성의 경계선
  OUTPUT  어떻게 보고하는가 — 형식과 언어

프롬프트에 도구 이름을 쓸 때는 실제 함수명과 정확히 일치시킨다. 어긋나면 모델이
없는 도구를 부르려다 실패한다.
"""

SECTIONS = ("ROLE", "TASK", "POLICY", "OUTPUT")


def compose(*, role: str, task: str, policy: str, output: str) -> str:
    """섹션을 태그로 감싸 하나의 시스템 프롬프트로 조립한다."""
    parts = {"ROLE": role, "TASK": task, "POLICY": policy, "OUTPUT": output}
    return "\n\n".join(f"[{name}]\n{parts[name].strip()}" for name in SECTIONS)
