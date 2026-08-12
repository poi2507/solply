import "dotenv/config";
import express from "express";
import { getBalances, isWalletName, sendUsdc, verifyTransaction } from "./solana.js";

const app = express();
app.use(express.json());

app.get("/health", (_req, res) => res.json({ ok: true }));

// 에이전트 지갑 잔액 조회 (SOL + USDC) — :wallet ∈ hq | store-a | store-b | store-c
app.get("/balance/:wallet", async (req, res) => {
  const { wallet } = req.params;
  if (!isWalletName(wallet)) {
    return res.status(400).json({ error: `알 수 없는 지갑: ${wallet}` });
  }
  try {
    res.json(await getBalances(wallet));
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// USDC 결제 실행 — 심사 기준: 시연 중 실제 트랜잭션 발생 + 실행 로그
app.post("/pay", async (req, res) => {
  const { from, recipient, amount, memo } = req.body ?? {};
  if (!from || !isWalletName(from)) {
    return res.status(400).json({ error: "from은 hq|store-a|store-b|store-c 중 하나여야 합니다" });
  }
  if (!recipient || !amount) {
    return res.status(400).json({ error: "recipient와 amount는 필수입니다" });
  }
  try {
    const result = await sendUsdc(from, recipient, Number(amount), memo ?? "");
    console.log(
      `[PAY] ${from} → ${recipient} | ${amount} USDC | ${memo ?? ""} | fee:${result.feePayer} | ${result.signature}`,
    );
    res.json({ status: "confirmed", ...result });
  } catch (e) {
    console.error("[PAY:ERROR]", e);
    res.status(500).json({ status: "failed", error: String(e) });
  }
});

// 수금 검증 — HQ 에이전트가 payment-submitted를 받으면 이 엔드포인트로 온체인 대조
app.get("/tx/:sig", async (req, res) => {
  try {
    const result = await verifyTransaction(req.params.sig);
    if (!result.found) return res.status(404).json(result);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

const port = Number(process.env.PORT ?? 3000);
app.listen(port, () =>
  console.log(`solply payments on :${port} (${process.env.SOLANA_NETWORK ?? "devnet"})`),
);
