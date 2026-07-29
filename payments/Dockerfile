# 결제 서비스 — 지갑 키를 쥔 유일한 프로세스.
# Cloud Run에 비공개(--no-allow-unauthenticated)로 배포하고 백엔드만 호출한다.
FROM node:24-slim

WORKDIR /app

# 의존성 레이어를 소스와 분리해 재빌드를 빠르게
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src

# 지갑 키는 이미지에 넣지 않는다 — Secret Manager를 이 경로에 마운트한다.
# 파일명은 <지갑>.json 그대로여야 한다 (src/solana.ts가 그 이름으로 읽는다).
ENV SOLPLY_WALLET_DIR=/secrets/wallets

# PORT는 Cloud Run이 주입한다 (src/index.ts가 읽음, 기본 3000)
CMD ["npm", "start"]
