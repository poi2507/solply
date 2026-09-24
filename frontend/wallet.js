// 방문자 자기 지갑(Phantom 확장, Solana devnet)으로 결제한다.
//
// 흐름: 서버가 청구(받을 곳·금액·메모) → 여기서 트랜잭션을 만들어 Phantom에 서명·전송을 맡김
//      → 서명을 서버에 알림 → 서버가 체인에서 대조한 뒤에야 재료를 판매로 기록한다.
// 수수료(SOL)는 방문자가 낸다 — "소비자 결제가 소비자를 솔라나로 들인다"(8/18 팀장 결정).
// 이 파일은 결제를 누를 때만 불러온다 — 대부분의 방문자는 web3 라이브러리를 받지 않는다.

const RPC = "https://api.devnet.solana.com";
const TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
const ATA_PROGRAM = "ATokenGPvbdGVxr1b2hGZbsiqW5xWby2xQx9uUkCAbnL";
const MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr";

export class WalletError extends Error {
  constructor(message, help) { super(message); this.help = help; }
}

export const HELP = {
  install: 'Install the <a href="https://phantom.com/download" target="_blank" rel="noopener">Phantom extension</a>, then reload this page.',
  testnet: "In Phantom open <b>Settings → Developer Settings → Testnet Mode</b> and choose <b>Solana Devnet</b>. This store runs on devnet — no real money moves.",
  sol: 'You need a little devnet SOL for the network fee: <a href="https://faucet.solana.com" target="_blank" rel="noopener">faucet.solana.com</a> (paste your address, pick Devnet).',
  usdc: 'You need devnet USDC: <a href="https://faucet.circle.com" target="_blank" rel="noopener">faucet.circle.com</a> → Solana Devnet → paste your address.',
};

export function provider() {
  const p = window.phantom?.solana;
  return p?.isPhantom ? p : null;
}

let web3 = null;
async function lib() {
  if (!web3) {
    const [w, b] = await Promise.all([
      import("https://esm.sh/@solana/web3.js@1.95.3"),
      import("https://esm.sh/buffer@6.0.3"),
    ]);
    web3 = { ...w, Buffer: b.Buffer };
  }
  return web3;
}

export async function connect() {
  const p = provider();
  if (!p) throw new WalletError("Phantom is not installed in this browser.", HELP.install);
  try {
    const { publicKey } = await p.connect();
    return publicKey.toString();
  } catch {
    throw new WalletError("The wallet connection was cancelled.", "");
  }
}

function ata(w, owner, mint) {
  const [addr] = w.PublicKey.findProgramAddressSync(
    [new w.PublicKey(owner).toBuffer(), new w.PublicKey(TOKEN_PROGRAM).toBuffer(), new w.PublicKey(mint).toBuffer()],
    new w.PublicKey(ATA_PROGRAM),
  );
  return addr;
}

/** 결제 전에 잔액을 본다 — 모자라면 어떻게 채우는지 알려준다 (서명 창을 헛되이 띄우지 않게). */
export async function preflight(address, mint, amountUsdc) {
  const w = await lib();
  const conn = new w.Connection(RPC, "confirmed");
  const owner = new w.PublicKey(address);
  const lamports = await conn.getBalance(owner);
  let usdc = 0;
  try {
    const bal = await conn.getTokenAccountBalance(ata(w, address, mint));
    usdc = Number(bal.value.uiAmount ?? 0);
  } catch { /* 토큰 계좌가 아직 없다 = USDC 0 */ }
  if (lamports < 20_000) throw new WalletError(`This wallet has no devnet SOL for the fee.`, HELP.sol);
  if (usdc + 1e-9 < amountUsdc) {
    throw new WalletError(`This wallet has ${usdc.toFixed(2)} devnet USDC; the order needs ${amountUsdc.toFixed(2)}.`, HELP.usdc);
  }
  return { sol: lamports / 1e9, usdc };
}

/** 청구대로 이체 + 메모(주문번호)를 한 트랜잭션에 담아 Phantom에 서명·전송을 맡긴다. */
export async function pay(address, payment) {
  const w = await lib();
  const conn = new w.Connection(RPC, "confirmed");
  const owner = new w.PublicKey(address);
  const amount = BigInt(payment.amount_base_units);
  const data = new Uint8Array(9);
  data[0] = 3; // SPL Token: Transfer
  new DataView(data.buffer).setBigUint64(1, amount, true);
  const transfer = new w.TransactionInstruction({
    programId: new w.PublicKey(TOKEN_PROGRAM),
    keys: [
      { pubkey: ata(w, address, payment.mint), isSigner: false, isWritable: true },
      { pubkey: new w.PublicKey(payment.recipient_token_account), isSigner: false, isWritable: true },
      { pubkey: owner, isSigner: true, isWritable: false },
    ],
    data: w.Buffer.from(data),
  });
  const memo = new w.TransactionInstruction({
    programId: new w.PublicKey(MEMO_PROGRAM), keys: [], data: w.Buffer.from(payment.memo, "utf-8"),
  });
  const tx = new w.Transaction().add(transfer, memo);
  tx.feePayer = owner;
  tx.recentBlockhash = (await conn.getLatestBlockhash("confirmed")).blockhash;
  try {
    const { signature } = await provider().signAndSendTransaction(tx);
    return signature;
  } catch (e) {
    const msg = String(e?.message ?? e);
    if (/reject|cancel|denied/i.test(msg)) throw new WalletError("You declined the transaction in Phantom.", "");
    throw new WalletError("Phantom could not send the transaction.", HELP.testnet);
  }
}
