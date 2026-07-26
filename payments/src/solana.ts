import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  TransactionInstruction,
} from "@solana/web3.js";
import {
  createTransferInstruction,
  getOrCreateAssociatedTokenAccount,
} from "@solana/spl-token";

const RPC_URL = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";
// Circle 공식 devnet USDC mint
const USDC_MINT = new PublicKey(
  process.env.USDC_MINT ?? "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
);
const USDC_DECIMALS = 6;
const MEMO_PROGRAM_ID = new PublicKey("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr");

// 에이전트 지갑 디렉터리: hq / store-a / store-b / store-c
const WALLET_DIR = (process.env.SOLPLY_WALLET_DIR ?? "~/.config/solana/solply").replace(
  "~",
  homedir(),
);
const WALLET_NAMES = ["hq", "store-a", "store-b", "store-c"] as const;
export type WalletName = (typeof WALLET_NAMES)[number];

export const connection = new Connection(RPC_URL, "confirmed");

export function isWalletName(name: string): name is WalletName {
  return (WALLET_NAMES as readonly string[]).includes(name);
}

export function loadKeypair(name: WalletName): Keypair {
  const raw = readFileSync(join(WALLET_DIR, `${name}.json`), "utf-8");
  return Keypair.fromSecretKey(Uint8Array.from(JSON.parse(raw)));
}

export async function getBalances(name: WalletName) {
  const wallet = loadKeypair(name);
  const sol = (await connection.getBalance(wallet.publicKey)) / 1e9;
  let usdc = 0;
  try {
    const ata = await getOrCreateAssociatedTokenAccount(
      connection,
      wallet,
      USDC_MINT,
      wallet.publicKey,
    );
    usdc = Number(ata.amount) / 10 ** USDC_DECIMALS;
  } catch {
    // SOL이 없어 ATA를 만들 수 없거나 아직 USDC 계정이 없으면 0
  }
  return { wallet: name, address: wallet.publicKey.toBase58(), sol, usdc };
}

export async function sendUsdc(
  fromName: WalletName,
  recipient: string,
  amount: number,
  memo: string,
) {
  const wallet = loadKeypair(fromName);
  const to = new PublicKey(recipient);

  const fromAta = await getOrCreateAssociatedTokenAccount(
    connection,
    wallet,
    USDC_MINT,
    wallet.publicKey,
  );
  const toAta = await getOrCreateAssociatedTokenAccount(connection, wallet, USDC_MINT, to);

  const tx = new Transaction().add(
    createTransferInstruction(
      fromAta.address,
      toAta.address,
      wallet.publicKey,
      BigInt(Math.round(amount * 10 ** USDC_DECIMALS)),
    ),
  );
  if (memo) {
    tx.add(
      new TransactionInstruction({
        keys: [],
        programId: MEMO_PROGRAM_ID,
        data: Buffer.from(memo, "utf-8"),
      }),
    );
  }

  const signature = await connection.sendTransaction(tx, [wallet]);
  await connection.confirmTransaction(signature, "confirmed");
  return {
    signature,
    from: wallet.publicKey.toBase58(),
    recipient,
    amount,
    memo,
    explorer: `https://explorer.solana.com/tx/${signature}?cluster=devnet`,
  };
}

/** HQ의 수금 검증용: 트랜잭션에서 USDC 전송량·수취인·memo를 파싱한다. */
export async function verifyTransaction(signature: string) {
  const tx = await connection.getParsedTransaction(signature, {
    commitment: "confirmed",
    maxSupportedTransactionVersion: 0,
  });
  if (!tx) return { found: false as const, signature };

  let transfer: { source: string; destination: string; amount: number } | null = null;
  let memo: string | null = null;

  for (const ix of tx.transaction.message.instructions) {
    if ("parsed" in ix) {
      if (ix.program === "spl-token" && ix.parsed?.type === "transfer") {
        transfer = {
          source: ix.parsed.info.source,
          destination: ix.parsed.info.destination,
          amount: Number(ix.parsed.info.amount) / 10 ** USDC_DECIMALS,
        };
      }
      if (ix.program === "spl-memo") {
        memo = typeof ix.parsed === "string" ? ix.parsed : String(ix.parsed);
      }
    }
  }

  return {
    found: true as const,
    signature,
    slot: tx.slot,
    blockTime: tx.blockTime ?? null,
    success: tx.meta?.err == null,
    transfer,
    memo,
    explorer: `https://explorer.solana.com/tx/${signature}?cluster=devnet`,
  };
}
