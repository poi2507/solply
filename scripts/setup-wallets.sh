#!/usr/bin/env bash
# Solply 에이전트 지갑 4개 생성 (본사 + 가맹점 3곳) 및 devnet SOL 에어드랍
set -euo pipefail
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"

DIR="$HOME/.config/solana/solply"
mkdir -p "$DIR"

for name in hq store-a store-b store-c; do
  KEY="$DIR/$name.json"
  if [ ! -f "$KEY" ]; then
    solana-keygen new --no-bip39-passphrase --silent --outfile "$KEY"
  fi
  ADDR=$(solana-keygen pubkey "$KEY")
  echo "$name: $ADDR"
  solana airdrop 1 "$ADDR" --url devnet >/dev/null 2>&1 && echo "  ✓ 1 SOL airdropped" || echo "  ✗ airdrop 실패 (faucet.solana.com 사용)"
done
