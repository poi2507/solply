import { readFileSync } from "node:fs";
import { homedir } from "node:os";
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
const MEMO_PROGRAM_ID = new PublicKey("MemoSq4gqABAXKb96qnH8TySNcWxMyWCqXgDLGmfcHr");

export const connection = new Connection(RPC_URL, "confirmed");

export function loadKeypair(): Keypair {
  const path = (process.env.SOLANA_KEYPAIR_PATH ?? "~/.config/solana/hackathon.json").replace(
    "~",
    homedir(),
  );
  return Keypair.fromSecretKey(Uint8Array.from(JSON.parse(readFileSync(path, "utf-8"))));
}

export async function getBalances() {
  const wallet = loadKeypair();
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
    // USDC 계정이 아직 없으면 0
  }
  return { address: wallet.publicKey.toBase58(), sol, usdc };
}

export async function sendUsdc(recipient: string, amount: number, memo: string) {
  const wallet = loadKeypair();
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
    explorer: `https://explorer.solana.com/tx/${signature}?cluster=devnet`,
  };
}
