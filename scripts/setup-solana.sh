#!/usr/bin/env bash
# Solana devnet 지갑 생성 및 설정
set -euo pipefail

KEYPAIR="$HOME/.config/solana/hackathon.json"

if [ ! -f "$KEYPAIR" ]; then
  solana-keygen new --no-bip39-passphrase --outfile "$KEYPAIR"
fi

solana config set --url devnet --keypair "$KEYPAIR"
solana airdrop 2 || echo "airdrop 실패 시 https://faucet.solana.com 사용"
solana balance

echo ""
echo "devnet USDC 받기: https://faucet.circle.com (Solana devnet 선택)"
echo "지갑 주소: $(solana address)"
