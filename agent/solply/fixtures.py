"""Mock 도메인 데이터(납품·검수·POS) 로더 — W3에 실제 이벤트 파이프라인으로 교체."""

import json
from pathlib import Path

_PATH = Path(__file__).parent.parent / "data" / "fixtures.json"


def load() -> dict:
    return json.loads(_PATH.read_text())
