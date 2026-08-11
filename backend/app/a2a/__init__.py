"""A2A (Agent-to-Agent) 경량판 — 에이전트 사이의 대화 통로를 표준으로.

card    에이전트 명함 (/.well-known/agent-card.json) — intent 목록이 곧 skills
server  message/send(JSON-RPC) 수신 → 기존 LangGraph 실행으로 번역. 그래프 무변경.
client  발신 — 상대 에이전트의 A2A 엔드포인트로 실제 HTTP 왕복

경량판은 자기 자신을 HTTP로 부른다 (x402 self-call과 같은 수법). 완전판 승격은
config의 A2A_*_URL 교체가 전부다 — 메시지 규약·번역기·클라이언트는 그대로.
"""
