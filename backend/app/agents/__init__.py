"""에이전트 계층.

  state.py     공통 상태 베이스 (BaseState) — 에이전트별 상태가 이걸 상속한다
  runner.py    그래프 실행기
  prompts.py   prompts/*.md 로더
  utils.py     조회·순수계산·기록 헬퍼
  hq/, store/  에이전트마다 graph.py · node.py · state.py · tools.py · prompts/
"""
