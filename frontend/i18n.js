// 화면 언어 — 기본 영어, `?lang=ko`로 한국어.
//
// 왜 DOM 단계에서 하는가: 화면 문자열이 여섯 파일의 템플릿 리터럴 수백 군데와
// 백엔드가 내려주는 라벨(overview.actionLabels 67개)에 흩어져 있다. 전부 t() 호출로
// 바꾸면 손댈 자리가 400곳이고 회귀 위험이 그만큼이다. 대신 렌더된 텍스트 노드를
// 한 번 훑어 사전대로 바꾼다 — 프론트와 백엔드 라벨이 같은 사전 하나로 덮이고,
// 되돌리려면 이 파일과 import 두 줄만 지우면 된다.
//
// 한국어로 보려면 주소에 ?lang=ko (한 번 주면 이 브라우저에 기억된다).

// ── 사전: 한국어 구 → 영어 ────────────────────────────────────────
// 긴 구부터 맞춰야 짧은 조각이 먼저 먹지 않는다 (아래 build()가 길이순 정렬).
const EN = {
  // 문서·역할 게이트
  "식자재 대금 자율 정산": "Autonomous settlement for food supply",
  "어느 입장으로 접속하시겠습니까": "Which role are you signing in as?",
  "역할에 따라 보이는 정보와 결정 권한이 다릅니다.":
    "What you see and what you may decide depends on the role.",
  "청구서를 발행하고 가맹점의 협상 제안을 심사합니다. 모든 지점의 미수금과 신용을 봅니다.":
    "Issues invoices and reviews stores' negotiation proposals. Sees every store's receivables and credit.",
  "본사가 보낸 청구서를 검증하고, 여력이 될 때 결제합니다. 다른 지점의 내역은 보이지 않습니다.":
    "Audits invoices from HQ and pays when it can afford to. Cannot see other stores' records.",
  "에이전트의 모든 판단 로그와 온체인 지갑 상태를 감사합니다. 거래에는 개입하지 않습니다.":
    "Audits every agent decision log and on-chain wallet. Does not intervene in trades.",
  "이 역할에는 아직 패스키가 없습니다.": "This role has no passkey yet.",
  "패스키 등록하고 입장": "Register a passkey and enter",
  "건너뛰기 (데모 모드)": "Skip (demo mode)",
  "등록하면 다음부터 지문·Face ID 한 번으로 들어옵니다.":
    "Once registered, a fingerprint or Face ID gets you in.",
  "지갑 열쇠는 본사가 안전하게 보관합니다 — 점주는 아무것도 외울 필요가 없습니다.":
    "HQ custodies the wallet keys — the store owner memorizes nothing.",
  "운영자가 아니라면 —": "Not an operator? —",
  "손님으로 구매해보기 →": "Try buying as a customer →",
  "여러분의 구매가 에이전트 조달을 일으킵니다.": "Your purchase triggers agent procurement.",
  "심사 중이시라면 —": "Judging? —",
  "에서 협상 기록·데이터 상점을": "for negotiation history and the data shop;",
  "에서 실행 로그와 무대 트리거를 보세요.": "for the activity log and demo triggers.",
  "본인확인이 완료되지 않았습니다 (": "Verification did not complete (",
  "등록이 완료되지 않았습니다 (": "Registration did not complete (",
  "다시 등록하거나 데모 모드로 입장하세요.": "Register again, or enter in demo mode.",
  "데모 모드로 입장할 수 있습니다.": "You can enter in demo mode.",
  "주체가 지정되지 않았습니다": "No role selected",

  // 역할 이름
  "본사 정산팀": "HQ Finance",
  "시스템 관리자": "System Administrator",
  "전 지점 청구·심사·정산": "Invoicing, review and settlement across all stores",
  "내 청구서·잔액·정책": "My invoices, balance and policy",
  "실행 증빙 · 지갑 · 네트워크": "Execution log · wallets · network",

  // 마스트헤드·공통
  "오늘로": "Today",
  "이전 날": "Previous day",
  "다음 날": "Next day",
  "이전 쪽": "Previous page",
  "다음 쪽": "Next page",
  "실시간 연결됨": "Live",
  "재연결 중": "Reconnecting",
  "실행 중": "Running",
  "생성 중": "Generating",
  "조회 중": "Loading",
  "불러오는 중": "Loading",
  "대기 중": "Waiting",
  "저장 (변경됨)": "Save (changed)",
  "닫기 (Esc)": "Close (Esc)",
  "관리 토큰을 입력하세요 (운영자 전용)": "Enter the admin token (operators only)",
  "연결에 실패했습니다.": "Connection failed.",
  "저장됐습니다. 다음 판단부터 적용됩니다.": "Saved. It applies from the next decision.",

  // 지표 타일
  "오늘 정산 완료 (USDC)": "Settled today (USDC)",
  "미결 전체": "Total open",
  "부가 수익": "Side revenue",
  "사람 개입": "Human interventions",
  "이 날 사람이 누른 횟수": "Times a human stepped in on this day",
  "전체 기간 발행": "Issued all-time",
  "누적 청구서": "Invoices to date",
  "로열티 수익": "Royalty revenue",
  "데이터 매출": "Data revenue",
  "건 · 데이터": " · data",
  "건 · 누적": " · to date",
  "건 누적": " to date",
  "건 기록됨": " recorded",
  "건 중": " of ",
  "회 분할": "-way split",

  // 자금 흐름도
  "오늘의 자금 흐름": "Today's money flow",
  "오늘 본사와 지점 사이를 오간 온체인 자금 흐름":
    "On-chain money that moved between HQ and the stores today",
  "오늘 내 지점을 중심으로 오간 온체인 자금 흐름":
    "On-chain money that moved through my store today",
  "물대·카드정산·P2P·데이터 판매가 오간 경로 — 숫자는 온체인 합계(USDC)":
    "Supply payables, card settlement, peer trades and data sales — figures are on-chain totals (USDC)",
  "청록 점선은 이웃 지점과의 P2P 직거래 — 초록 유입 · 파랑 유출 (내 지갑 기준)":
    "Teal dashes are peer trades with neighbouring stores — green in, blue out (from my wallet)",
  "모든 흐름은": "Every flow is",
  "점선은 지점": "Dashes are store",
  "손님 매출": "Customer sales",
  "손님 지갑에서 본사로": "From the customer wallet to HQ",
  "가 온체인 이체": " transferred on-chain",
  "매출은 금고 적립 후": "Sales accrue in the till, then",
  "로열티 공제하고 지급": "are paid out less royalty",
  "로열티 원천징수": "Royalty withheld",
  "카드정산 대기": "Awaiting card settlement",
  "본사 창고": "HQ warehouse",
  "내 지점": "My store",
  "카드정산": "Card settlement",
  "시세 구입": "Price data bought",
  "지수 인도": "Index delivered",
  "지수 판매": "Index sold",
  "데이터 판매": "Data sales",
  "방문 구매": "Visitor purchases",

  // 가맹점 현황
  "가맹점 현황": "Stores",
  "가맹점 정보가 없습니다": "No store data",
  "신용점수는 온체인 납부 이력에서 계산됩니다": "Credit score is computed from on-chain payment history",
  "본사가 보는 내 신용 상태": "How HQ sees my credit",
  "내 신용점수": "My credit score",
  "신용점수": "Credit score",
  "납부 이력 기준": "based on payment history",
  "정시납": "on time",
  "연체": "late",
  "분쟁": "disputed",
  "미수금": "Outstanding",
  "정산 완료": "Settled",
  "자동결제 한도": "Auto-pay limit",
  "결제 가능액": "Available to pay",
  "납부할 금액": "Amount due",
  "지갑 잔액": "Wallet balance",
  "안전재고 미달": "below safety stock",
  "안전재고": "safety stock",
  "현재고": "on hand",

  // 소비 패턴
  "소비 패턴": "Demand pattern",
  "전 지점 소비 패턴": "Demand across all stores",
  "소비 패턴을 불러오지 못했습니다": "Could not load the demand pattern",
  "최근 7일 판매 기록이 없습니다": "No sales in the last 7 days",
  "최근 7일 소비 (": "Last 7 days (",
  "최근 7일 판매": "last 7 days",
  "추세는 직전 7일 대비 — 에이전트의 발주량 근거와 같은 원장":
    "Trend is versus the previous 7 days — the same ledger the agent uses to size orders",
  "개/7일": "/7d",
  "첫 창": "first window",

  // 청구서·협상
  "청구서": "Invoices",
  "내 청구서": "My invoices",
  "이 날짜에는 청구서가 없습니다. 날짜를 옮기거나 데모를 실행해 보세요.":
    "No invoices on this date. Move the date, or run the demo.",
  "이 날은 청구서가 없습니다": "No invoices on this day",
  "행을 누르면 협상 과정이 펼쳐집니다": "Open a row to see how the negotiation went",
  "과정을 불러오지 못했습니다": "Could not load the trail",
  "기록된 단계가 없습니다": "No steps recorded",
  "협상 기록": "Negotiations",
  "내 협상 기록": "My negotiations",
  "협상 기록이 없습니다": "No negotiations",
  "최근 협상 경위": "How the latest negotiations went",
  "에이전트가 제안하고 심사한 결과": "What the agents proposed and how it was reviewed",
  "에이전트 협상": "Agent negotiation",
  "협상 진행 중": "Negotiating",
  "협상 결렬": "Talks broke down",
  "지점 판단": "Store decision",
  "본사 판단": "HQ decision",
  "사람 승인 대기": "Awaiting human approval",
  "승인 대기": "Pending approval",
  "정책 상한을 넘어 에이전트가 멈춘 결제 — 여기가 자율성의 경계":
    "Payments the agent stopped at the policy ceiling — this is where autonomy ends",
  "자동결제 상한을 넘어 에이전트가 결제를 보류했습니다 — 사람이 결정할 지점입니다":
    "Over the auto-pay ceiling, so the agent held the payment — a human decides here",
  "발주 기록에 없어 에이전트가 결제를 거부했습니다 — 재발행하거나 거부를 확정할 사람의 몫입니다":
    "No matching order, so the agent refused to pay — a human reissues it or confirms the refusal",
  "거부 검토": "Review refusal",
  "거부 확정": "Confirm refusal",
  "재발행": "Reissue",
  "반려": "Reject",
  "금액 정정됨": "Amount corrected",
  "역제안 수락": "Counter-offer accepted",
  "수정안 수용 — 분할 청구서 집행": "Revision accepted — installment invoices issued",
  "수정안 거절 — 사람 결정 대기": "Revision declined — waiting on a human",
  "수정안 — 지금": "Revision — now",
  "분할 역제안 — 지점 응답 대기": "Installment counter-offer — awaiting the store",
  "유예 수락 — 예약 전환": "Deferral accepted — scheduled",
  "유예 거절": "Deferral declined",
  "결렬 — 분할도 감당 불가": "Broke down — cannot manage even in installments",
  "결렬 — 사람 결정 대기": "Broke down — waiting on a human",
  "납부 유예 요청": "Deferral requested",
  "재응수": "Reply",
  "선납": "Upfront",
  "종결": "Closed",
  "이 날 자동 합의": "Settled automatically on this day",

  // 예약 납부
  "예약 납부": "Scheduled payments",
  "유예·분할 합의로 예약된 결제 — 운영에선 Cloud Scheduler가 실행합니다":
    "Payments scheduled by a deferral or installment agreement — Cloud Scheduler runs them in production",
  "예약일이 오면 에이전트가 x402 왕복으로 결제합니다":
    "On the due date the agent pays over an x402 round trip",
  "납부 완료": "Paid",

  // 직거래
  "지점 간 직거래": "Peer trades between stores",
  "지점 직거래(P2P) — 오늘": "Peer trades (P2P) — today",
  "가맹점끼리 협상하고 본사가 승인한 P2P 재고 거래":
    "Stock traded store to store, negotiated by them and approved by HQ",
  "재고 부족분을 옆 지점에서 조달 — 시세 지수 근거 · x402 결제":
    "Shortfalls sourced from a neighbouring store — priced off the index, paid over x402",
  "이 날짜에는 지점 간 직거래가 없습니다": "No peer trades on this date",
  "이 날은 지점 간 직거래가 없습니다": "No peer trades on this day",
  "직거래 에스크로 — 예치 중 금액": "Peer-trade escrow — amount held",
  "직거래 흥정": "Peer-trade haggling",
  "본사 중개": "HQ brokerage",
  "중개 응답 (지점)": "Brokerage reply (store)",
  "온체인 정산이 확인된 체결만": "Only trades confirmed on-chain.",

  // 재고 원장
  "재고 원장": "Stock ledger",
  "재고 데이터가 없습니다": "No stock data",
  "아직 재고 이동이 없습니다": "No stock movements yet",
  "입고 · 출고 · 판매 · 지점 간 이동이 전부 기록으로 남습니다":
    "Receipts, shipments, sales and store-to-store moves are all recorded",
  "최근 이동": "Recent moves",
  "아직 판매 기록이 없습니다": "No sales recorded yet",

  // 데이터 상점
  "데이터 상점": "Data shop",
  "데이터 상점 구매자": "Data shop buyers",
  "데이터 거래처 — 지수 구매": "Data counterparties — index purchases",
  "실거래가 남긴 지수를 x402로 판다 (pay.sh와 같은 규약 · 카탈로그 입점은 메인넷 전환 시) — 에이전트도 여기서 판단 재료를 산다":
    "Indices built from real trades, sold over x402 (same protocol as pay.sh; catalog listing waits for mainnet) — our own agents buy their inputs here too",
  "비식별 집계하며, 에이전트도 같은 상점에서 판단 재료를 사 간다 (자급 순환).":
    "Aggregated and de-identified; our agents buy their inputs from the same shop (a closed loop).",
  "체결가 지수": "Price index",
  "수요 지수": "Demand index",
  "지수 1건 가격 (USDC)": "Price per index call (USDC)",
  "상품 2종 —": "2 products —",
  "자급": "self-supplied",
  "외부": "external",
  "매입": "bought",

  // 어시스턴트
  "정산 어시스턴트": "Settlement assistant",
  "어시스턴트": "Assistant",
  "정산 현황을 물어보거나 승인·예약 실행을 맡겨 주세요.":
    "Ask about settlement, or hand off an approval or a scheduled run.",
  "조회와 승인을 대화로": "Look things up and approve, by chatting",
  "메시지 입력": "Type a message",
  "이번 주 정산 요약해줘": "Summarize this week's settlement",
  "승인 대기 있어": "Anything waiting for approval?",
  "최근 협상 어떻게 진행됐어": "How did the recent negotiations go?",
  "이번 주 요약": "This week",
  "아직 활동이 없습니다": "No activity yet",
  "응답 실패": "No response",

  // 정책
  "거래 정책": "Trading policy",
  "내 거래 정책": "My trading policy",
  "에이전트의 판단 경계": "The boundary of the agent's judgment",
  "에이전트는 이 범위 안에서만 스스로 판단합니다. 넘으면 사람에게 넘깁니다.":
    "The agent decides on its own only inside these bounds. Past them, it hands over to a human.",
  "에이전트에게 문장으로 지시하세요 — 숫자 한도는 정책 숫자가 강제합니다":
    "Steer the agent in plain sentences — the numeric limits below are what actually binds it",
  "정책을 불러오지 못했습니다": "Could not load the policy",
  "직접 작성": "Write your own",
  "크게 편집": "Edit in a larger box",

  // 실행 로그·리포트
  "실행 로그": "Activity log",
  "최근 활동": "Recent activity",
  "정산 리포트": "Settlement report",
  "이번 주기 처리 내역 요약 — 결과는 창으로 뜹니다.":
    "A summary of this cycle — the result opens in a window.",
  "요약을 작성하고 있습니다": "Writing the summary",
  "아직 요약할 정산 내역이 없습니다.": "Nothing settled to summarize yet.",
  "리포트 생성에 실패했습니다. 잠시 뒤 다시 시도해 주세요.":
    "Could not generate the report. Please try again shortly.",
  "시연 실행": "Run demo",
  "협상 시연": "Demo a negotiation",
  "실제 거래가 발생합니다": "A real trade will happen",
  "지금 실행": "Run now",
  "틱 실행 중": "Tick running",
  "틱 실행됨": "Tick ran",
  "틱 실행": "Run tick",
  "에이전트 작동 중": "Agents at work",

  // 지갑·체인
  "지갑": "Wallets",
  "내 지갑": "My wallet",
  "손님 지갑 — /shop 구매 유입": "Customer wallet — inflow from /shop purchases",
  "손님 (guest)": "Customer (guest)",
  "온체인 잔액 조회 중": "Reading on-chain balances",
  "잔액 조회가 늦어지고 있습니다 — 잠시 후 자동 갱신됩니다":
    "Balances are slow to load — this refreshes itself shortly",
  "결제 서비스 연결 안 됨": "Payments service unreachable",
  "온체인 트랜잭션": "On-chain transaction",
  "온체인 USDC 이체": "On-chain USDC transfer",
  "온체인 영수증 ↗": "on-chain receipt ↗",
  "온체인 정산": "On-chain settlement",
  "체인↗": "chain ↗",
  "영수증": "Receipt",
  "트랜잭션": "Transaction",
  "네트워크": "Network",
  "모든 결제는 Solana 온체인에서 실행되며, 각 판단은 실행 로그로 남습니다.":
    "Every payment executes on Solana, and every decision is written to the activity log.",
  "명함": "Agent card",
  "저장소": "Datastore",
  "대시보드": "Dashboard",

  // 상점 (/shop)
  "스토어 — 손님으로 참여하기": "Store — take part as a customer",
  "여기서의 구매는 진짜 수요가 됩니다 — 재고가 안전선을 깨면":
    "A purchase here is real demand — when stock breaks the safety line,",
  "지점 에이전트가 스스로 조달(직거래·발주)을 시작하고 온체인으로 정산":
    "the store's agent starts procuring on its own (peer trade or HQ order) and settles on-chain",
  "합니다. 여러분이 누른 버튼이": ". The button you press,",
  "그 자리에서": "right then,",
  "에이전트 상거래를 일으킵니다 — 아래 실시간 기록과": "sets off agent commerce — watch it below and on the",
  "에서 지켜보세요.": ".",
  "재고가 안전선(눈금) 아래로 내려가면 에이전트가 그 자리에서 조달을 시작합니다":
    "when stock drops below the safety line (the tick mark), the agent starts procuring right away",
  "진열대를 불러오는 중": "Loading the shelves",
  "품절 — 에이전트가 채우는 중": "Sold out — the agent is restocking",
  "개 남음": " left",
  "개 구매": " to cart",
  "내 지갑 (손님)": "My wallet (customer)",
  "조회 지연 — 잠시 후 갱신": "Slow to load — refreshing shortly",
  "수수료 없음 — 가게가 대납합니다": "No fees — the store pays them",
  "수수료 본사 대납": "HQ pays the fee",
  "구매 완료": "Purchase complete",
  "구매 실패": "Purchase failed",
  "동작 원리": "How it works",
  "구매 버튼을 누르면": "Press buy and",
  "손님 지갑에서 본사로": "USDC moves on-chain from the customer wallet to HQ",
  "되고(영수증 링크 제공), 매출은 지점 금고에 적립됐다가 다음 정산 틱에 로열티를 공제한 뒤":
    " (with a receipt link). The sale accrues in the store's till and, on the next settlement tick, is paid out less royalty",
  "지점에 지급됩니다. 구매 → 재고 감소 → 에이전트 조달 → x402 정산의 전 과정이 실행 증빙으로 남습니다.":
    ". Purchase → stock drop → agent procurement → x402 settlement: the whole chain is left as evidence.",
  "에서 내 가게 구매": "buy from my store at",

  // 상점 실시간 패널
  "실시간 기록 — 구매 직후 이 지점의 에이전트 활동이 쌓이는 자리.":
    "Live log — this store's agent activity, right after your purchase.",
  "에이전트가 지금 움직입니다": "agents are moving now",
  "에이전트가 움직이는 중": "Agents at work",
  "도는 틱이 곧 조달을 처리합니다": "the running tick will handle procurement shortly",
  "실행 기록이 도착하는 대로 여기 쌓입니다": "Events pile up here as they arrive",
  "조달이 끝났습니다 — 청구서와 정산 내역은 대시보드에서 확인하세요":
    "Procurement finished — see the invoice and settlement on the dashboard",
  "이번 조달은 실패로 기록됐습니다 — 다음 틱이 다시 시도합니다":
    "This round was recorded as a failure — the next tick retries",
  "기록은 대시보드 실행 로그에서 계속 볼 수 있습니다":
    "You can keep watching in the dashboard's activity log",

  // 백엔드가 내려주는 손님 구매 안내문
  "재고가 안전선 아래로 내려갔습니다 — 지점 에이전트가 지금 조달을 시작합니다.":
    "Stock fell below the safety line — the store's agent is starting procurement now.",
  "재고가 안전선 아래로 내려갔습니다 — 지금 도는 틱이 곧 이 지점의 조달을 처리합니다.":
    "Stock fell below the safety line — the tick already running will handle this store shortly.",
  "재고가 안전선 아래로 내려갔습니다 — 다음 틱(10분 내)에 에이전트가 조달을 시작합니다.":
    "Stock fell below the safety line — the agent starts procuring on the next tick (within 10 minutes).",
  "매출이 적립됐습니다 — 다음 카드정산 틱에 온체인으로 지급됩니다.":
    "The sale accrued — it pays out on-chain at the next card-settlement tick.",

  // 백엔드 행위 라벨 (overview.actionLabels)
  "패스키 등록": "Passkey registered",
  "패스키 초기화": "Passkey reset",
  "패스키 본인확인": "Passkey verified",
  "에스크로 예치": "Escrow deposited",
  "에스크로 지급": "Escrow released",
  "에스크로 환불": "Escrow refunded",
  "인도 실패": "Delivery failed",
  "손님 구매 결제": "Customer purchase paid",
  "손님 결제 실패": "Customer payment failed",
  "손님 구매가 조달을 촉발": "Customer purchase triggered procurement",
  "손님 구매 → 조달 완료": "Customer purchase → procurement done",
  "손님 구매 → 조달 실패": "Customer purchase → procurement failed",
  "손님 주문 (온체인 결제)": "Customer order (paid on-chain)",
  "청구서 발행": "Invoice issued",
  "청구 금액 정정": "Invoice amount corrected",
  "분할 청구서 생성": "Installment invoices created",
  "검수 대조": "Delivery checked",
  "차감 제안": "Deduction proposed",
  "유예 제안": "Deferral proposed",
  "본사 심사": "HQ review",
  "역제안 응답 (지점)": "Counter-offer reply (store)",
  "협상 결렬 (사람에게)": "Negotiation broke down (to a human)",
  "발주량 응답 (지점)": "Order-quantity reply (store)",
  "직거래 가격 역제안": "Peer-trade price countered",
  "직거래 가격 합의": "Peer-trade price agreed",
  "직거래 가격 결렬": "Peer-trade price talks failed",
  "본사 직거래 중개": "HQ brokered a peer trade",
  "결제 실행": "Payment executed",
  "수금 검증": "Receipt verified",
  "검증 불일치": "Verification mismatch",
  "결제 거부": "Payment refused",
  "한도 초과 차단": "Blocked over limit",
  "사람 승인 요청": "Human approval requested",
  "결제 실패 (재시도 예정)": "Payment failed (will retry)",
  "x402 결제 요구 (402)": "x402 payment required (402)",
  "x402 조건 수신": "x402 terms received",
  "x402 정산 완료": "x402 settled",
  "x402 검증 실패": "x402 verification failed",
  "사람이 승인": "Approved by a human",
  "사람이 반려": "Rejected by a human",
  "거래 정책 변경": "Trading policy changed",
  "직거래 제안": "Peer trade proposed",
  "직거래 응답": "Peer trade answered",
  "본사 직거래 심사": "HQ reviewed the peer trade",
  "직거래 대금 요구": "Peer-trade payment required",
  "직거래 대금 결제": "Peer-trade payment made",
  "직거래 장부 반영": "Peer trade posted to the ledger",
  "직거래 검증 실패": "Peer-trade verification failed",
  "직거래 한도 초과 차단": "Peer trade blocked over limit",
  "본사 미승인 직거래 차단": "Peer trade blocked, not approved by HQ",
  "데이터 판매 견적 (402)": "Data sale quoted (402)",
  "데이터 판매 (x402 정산)": "Data sold (x402 settled)",
  "A2A 메시지 (message/send)": "A2A message (message/send)",
  "판매 (재고 차감)": "Sale (stock drawn down)",
  "카드매출 정산 지급": "Card revenue settled to the store",
  "손님 카드매출 수납 (시뮬)": "Customer card revenue collected (simulated)",
  "손님 지갑 자동 보충 (환류)": "Customer wallet topped up (recycled)",
  "카드정산 지급 실패 (재시도 예정)": "Card settlement failed (will retry)",
  "본사 창고 재입고": "HQ warehouse restocked",
  "시세 데이터 구매 (pay.sh)": "Price data bought (pay.sh)",
  "경제 루프 한 바퀴": "One turn of the economy loop",
  "직거래 입고": "Peer trade in",
  "직거래 출고": "Peer trade out",
  "창고 재입고": "Warehouse restocked",

  // 옛 기록에 남은 한글 품목·지점명 (fixtures는 영어로 바뀌었지만
  //  이미 발행된 청구서·재고 이동에는 그때의 이름이 박혀 있다)
  "냉장 닭 10kg": "Chicken (1 bird)",
  "모둠 야채 5kg": "Fresh vegetables",
  "시그니처 소스 1box": "Signature sauce",
  "튀김유 18L": "Frying oil (top-up)",
  "튀김가루 20kg": "Batter mix",
  "치킨무 3kg": "Pickled radish",
  "탄산음료 24캔": "Soda (can)",
  "포장 박스 50매": "Takeout box",
  "A지점 (강남)": "Store A (Gangnam)",
  "B지점 (홍대)": "Store B (Hongdae)",
  "C지점 (부산)": "Store C (Busan)",

  // 상태·판정 라벨
  "제안됨": "Proposed",
  "수락": "Accepted",
  "거절": "Declined",
  "본사 승인": "Approved by HQ",
  "확정": "Confirmed",
  "환불됨": "Refunded",
  "발행": "Issued",
  "결제됨": "Paid",
  "정산완료": "Settled",
  "협의중": "In discussion",
  "예약": "Scheduled",
  "거부": "Refused",
  "분할됨": "Split",
  "역제안": "Counter-offer",
  "원수량 고수": "Held the quantity",
  "본사 발주로": "Ordered from HQ",
  "발주량 심사": "Order-quantity review",
  "차감": "Deduction",
  "유예": "Deferral",
  "분할": "Installment",
  "정상": "Normal",
  "일치": "Match",
  "불일치": "Mismatch",
  "이행": "Fulfilled",
  "심사": "Review",
  "승인": "Approve",
  "요청": "Request",
  "주문": "Order",
  "납품": "Delivery",
  "원본": "Original",
  "완료 —": "Done —",
  "실패 —": "Failed —",
  "오류 —": "Error —",

  // 짧은 공통어
  "본사": "HQ",
  "지점": "Store",
  "가맹점": "Store",
  "물대": "supply payables",
  "청구서 ": "invoice ",
  "판매": "Sales",
  "시세": "Market price",
  "금액": "Amount",
  "품목": "Item",
  "수준": "Level",
  "상태": "Status",
  "오늘": "Today",
  "이 날": "on this day",
  "회차": "Round",
  "협상": "Negotiation",
  "정산": "Settlement",
  "저장": "Save",
  "닫기": "Close",
  "생성": "Generate",
  "편집": "Edit",
  "전환": "Switch",
  "전송": "Send",
  "펼치기": "Expand",
  "접기": "Collapse",
  "대비": "vs",
  "안전": "safety",
  "온체인": "on-chain",
  "점": "pt",
  "로열티": "Royalty",
  "관리자": "Admin",
  "시스템": "System",
  "스토어": "Store",
  "협상 (message/send": "Negotiation (message/send",
  "체결가 지수 — x402 구매": "Price index — bought over x402",
  "협상 기록에 표시)": "shown in the negotiation log)",
  "공용 style.css에 .live/.dot 같은 이름이 있어 상점 전용 접두사(sl-)를 쓴다": "",
};

// 숫자 뒤 단위는 영어에서 대개 생략한다 — 3,852건 → 3,852
const COUNTERS = [
  [/(\d)\s*건/g, "$1"],
  [/(\d)\s*회(?!차)/g, "$1"],
  [/(\d)\s*개(?!\s*남음)/g, "$1"],
  [/(\d)\s*명/g, "$1"],
  [/(\d)\s*점(?!검)/g, "$1 pt"],
];

// ── 언어 결정 ─────────────────────────────────────────────────────
const KEY = "solply.lang";
function currentLang() {
  let q = null;
  try {
    q = new URLSearchParams(location.search).get("lang");
  } catch { /* 주소를 못 읽어도 기본값으로 산다 */ }
  if (q === "ko" || q === "en") {
    try { localStorage.setItem(KEY, q); } catch { /* 사생활 보호 모드 */ }
    return q;
  }
  try { return localStorage.getItem(KEY) || "en"; } catch { return "en"; }
}

export const lang = currentLang();

// ── 치환기 ────────────────────────────────────────────────────────
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function build() {
  // 긴 구가 먼저 와야 짧은 조각이 가로채지 않는다.
  // 정규식 대체는 "같은 위치에서 먼저 쓰인 가지"가 이기므로 길이 내림차순이면 된다.
  const keys = Object.keys(EN).filter((k) => k.trim()).sort((a, b) => b.length - a.length);
  return new RegExp(keys.map(esc).join("|"), "g");
}
const RE = build();

// 숫자를 끼워 만든 요약 문장 — 사전 치환보다 먼저 돈다 (사전이 조각을 먼저 먹지 않게)
const PATTERNS_RAW = [
  [/발주 (.+?) (\d+)개 \(기본 (\d+)개\) 심사/g, "Order review: $1 ×$2 (base $3)"],
  [/검수 불일치분 ([\d.]+) USDC 차감 요청/g, "Deduction request: $1 USDC for the delivery mismatch"],
  [/납부 유예 요청 \((.+?)\)/g, "Deferral request ($1)"],
  [/(store-[a-z]) → (store-[a-z]) (.+?) (\d+)개 중개 제안/g, "Brokered trade: $1 → $2, $3 ×$4"],
  [/직거래 단가 ([\d.]+) → ([\d.]+) USDC 역제안/g, "Peer-trade counter: unit price $1 → $2 USDC"],
  [/역제안 단가 ([\d.]+) USDC에 대한 구매측 응답/g, "Buyer's reply to counter price $1 USDC"],
  [/선납 후 잔여 노출 (\d+)% ≤ 허용 ([\d.]+)% — 수정안 수용/g, "Exposure after upfront payment $1% ≤ allowed $2% — revision accepted"],
];
const PRE_EN = {
  "지점 수정안(선납 분할)": "Store's revision (upfront + installments)",
  "본사 분할 역제안에 대한 지점 응답": "Store's reply to HQ's installment counter-offer",
  "본사의 발주 수량 축소 제안에 대한 지점 응답": "Store's reply to HQ's order-quantity trim",
  "본사 중개 직거래에 대한 구매측 응답": "Buyer's reply to an HQ-brokered trade",
  "시점 미지정": "no date given",
};
const PATTERNS = PATTERNS_RAW;

// 숫자와 떨어져 제 요소에 홀로 있는 단위 (role.js의 unit:"건") — 영어에선 지운다
const BARE_UNIT = /^\s*(건|회|개|명|종|장)\s*$/;

export function translate(text) {
  if (!text || !/[가-힣]/.test(text)) return text;
  if (BARE_UNIT.test(text)) return "";
  // 코드가 숫자를 끼워 만드는 협상 요약 — 사전으로는 못 잡아 패턴으로 옮긴다 (hq/node.py·economy.py·store/tools.py)
  let out = text;
  for (const [ko, en] of Object.entries(PRE_EN)) out = out.split(ko).join(en);
  for (const [re, to] of PATTERNS) out = out.replace(re, to);
  out = out.replace(RE, (m) => EN[m] ?? m);
  for (const [re, to] of COUNTERS) out = out.replace(re, to);
  // 한국어는 "이 날 3건", 영어는 "3 on this day" — 사전은 자리를 못 바꾸므로 여기서 뒤집는다
  out = out.replace(/\bon this day\s+([\d,.]+)/g, "$1 on this day");
  return out;
}

// 번역하면 안 되는 곳: 스크립트·스타일·사용자가 타이핑하는 칸
const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE"]);
const ATTRS = ["title", "aria-label", "placeholder"];

function translateEl(el) {
  for (const a of ATTRS) {
    const v = el.getAttribute?.(a);
    if (v && /[가-힣]/.test(v)) {
      const t = translate(v);
      if (t !== v) el.setAttribute(a, t);
    }
  }
}

export function translateTree(root) {
  if (lang === "ko" || !root) return;
  if (root.nodeType === Node.TEXT_NODE) {
    const t = translate(root.nodeValue);
    if (t !== root.nodeValue) root.nodeValue = t;
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      SKIP.has(n.parentNode?.nodeName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const nodes = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n);
  for (const n of nodes) {
    const t = translate(n.nodeValue);
    if (t !== n.nodeValue) n.nodeValue = t;
  }
  if (root.querySelectorAll) {
    if (root.nodeType === Node.ELEMENT_NODE) translateEl(root);
    for (const el of root.querySelectorAll("[title],[aria-label],[placeholder]")) translateEl(el);
  }
}

// ── 시작 ──────────────────────────────────────────────────────────
// 화면은 fetch 결과로 계속 다시 그려진다 — 관찰자를 붙여 새로 들어온 것만 훑는다.
export function startI18n() {
  if (lang === "ko") return;
  document.documentElement.lang = "en";
  const run = () => {
    if (document.title) document.title = translate(document.title);
    translateTree(document.body);
    new MutationObserver((muts) => {
      for (const m of muts) {
        if (m.type === "characterData") {
          const t = translate(m.target.nodeValue);
          if (t !== m.target.nodeValue) m.target.nodeValue = t;
        } else if (m.type === "attributes") {
          translateEl(m.target);
        } else {
          for (const n of m.addedNodes) translateTree(n);
        }
      }
    }).observe(document.body, {
      childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ATTRS,
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
}
