import { existsSync, readFileSync } from "node:fs";
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
// guest — 손님, trader — 데이터 상점 외부 거래처, escrow — P2P 직거래 예치금 금고.
// 셋 다 Gasless 대납 덕에 SOL 없이 USDC만 있으면 된다. escrow 잔액은
// "지금 예치 중인 직거래 대금"과 정확히 일치해야 한다 — 온체인이 곧 감사 장부.
const WALLET_NAMES = ["hq", "store-a", "store-b", "store-c", "guest", "trader", "escrow"] as const;
export type WalletName = (typeof WALLET_NAMES)[number];

// Gasless — 트랜잭션 수수료(SOL)와 토큰 계좌(ATA) 생성비를 대납하는 지갑.
// 지점은 SOL 0으로도 USDC를 낼 수 있다: 점주는 가스가 뭔지 몰라도 된다 (결선 기준 2).
// 빈 문자열이면 예전처럼 보내는 지갑이 자기 수수료를 낸다.
// (완전판 A2A로 지갑 키가 회사별로 갈라지면, 대납은 본사 쪽 결제 서비스가
//  fee-payer 서명만 제공하는 별도 협력 흐름이 된다 — 경량판에서는 같은 금고라 단순하다.)
const FEE_PAYER = (process.env.FEE_PAYER_WALLET ?? "hq") as WalletName | "";

export const connection = new Connection(RPC_URL, "confirmed");

export function isWalletName(name: string): name is WalletName {
  return (WALLET_NAMES as readonly string[]).includes(name);
}

export function loadKeypair(name: WalletName): Keypair {
  // 평평한 배치(로컬: <dir>/hq.json)를 먼저, 지갑별 하위 디렉터리(<dir>/hq/hq.json)를 다음에.
  // Cloud Run은 한 디렉터리에 시크릿 하나만 마운트할 수 있어 운영에선 후자가 된다.
  const flat = join(WALLET_DIR, `${name}.json`);
  const nested = join(WALLET_DIR, name, `${name}.json`);
  const raw = readFileSync(existsSync(flat) ? flat : nested, "utf-8");
  return Keypair.fromSecretKey(Uint8Array.from(JSON.parse(raw)));
}

// 잔액 캐시 — 대시보드가 폴링할 때마다 지갑 7개 × (SOL + 토큰계좌)를 체인에 물으면
// RPC 한도에 걸린다 (8/15: 공용·전용 RPC 모두 429). 짧게 캐시하고, **돈이 움직이면
// 즉시 버린다** — 정산 판단이 낡은 잔액을 보면 본사 가용액을 넘겨 지급할 수 있다.
const BALANCE_TTL_MS = 15_000;
const balanceCache = new Map<string, { at: number; value: Awaited<ReturnType<typeof readBalances>> }>();

export function invalidateBalances() {
  balanceCache.clear();
}

export async function getBalances(name: WalletName) {
  const hit = balanceCache.get(name);
  if (hit && Date.now() - hit.at < BALANCE_TTL_MS) return hit.value;
  const value = await readBalances(name);
  balanceCache.set(name, { at: Date.now(), value });
  return value;
}

async function readBalances(name: WalletName) {
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

  // Gasless: 수수료·계좌 생성비는 대납 지갑이, 이체 서명은 보내는 지갑이.
  const gasless = FEE_PAYER !== "" && FEE_PAYER !== fromName;
  const feePayer = gasless ? loadKeypair(FEE_PAYER as WalletName) : wallet;

  const fromAta = await getOrCreateAssociatedTokenAccount(
    connection,
    feePayer,
    USDC_MINT,
    wallet.publicKey,
  );
  const toAta = await getOrCreateAssociatedTokenAccount(connection, feePayer, USDC_MINT, to);

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

  tx.feePayer = feePayer.publicKey;
  const signature = await connection.sendTransaction(
    tx,
    gasless ? [feePayer, wallet] : [wallet],
  );
  await connection.confirmTransaction(signature, "confirmed");
  invalidateBalances();  // 돈이 움직였다 — 다음 조회는 체인에서 다시 읽는다
  return {
    signature,
    from: wallet.publicKey.toBase58(),
    recipient,
    amount,
    memo,
    feePayer: gasless ? (FEE_PAYER as string) : fromName,
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
    // 수수료를 누가 냈는가 — 첫 계정이 fee payer라는 것이 솔라나 규약이다 (Gasless 증빙)
    feePayer: tx.transaction.message.accountKeys[0]?.pubkey?.toBase58?.() ?? null,
    explorer: `https://explorer.solana.com/tx/${signature}?cluster=devnet`,
  };
}
