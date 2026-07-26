"""Mock 도메인 데이터(납품·검수기록·POS 예측) 로더.

파이널 진출 후 실제 이벤트 파이프라인(Pub/Sub)으로 교체할 자리다.
"""

import json

from app import config


def load() -> dict:
    return json.loads(config.FIXTURES_PATH.read_text())
