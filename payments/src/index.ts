import "dotenv/config";
import express from "express";
import { getBalances, sendUsdc } from "./solana.js";

const app = express();
app.use(express.json());

app.get("/health", (_req, res) => res.json({ ok: true }));

// 에이전트 지갑 잔액 조회 (SOL + USDC)
app.get("/balance", async (_req, res) => {
  try {
    res.json(await getBalances());
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// USDC 결제 실행 — 심사 기준: 시연 중 실제 트랜잭션 발생 + 실행 로그
app.post("/pay", async (req, res) => {
  const { recipient, amount, memo } = req.body ?? {};
  if (!recipient || !amount) {
    return res.status(400).json({ error: "recipient와 amount는 필수입니다" });
  }
  try {
    const result = await sendUsdc(recipient, Number(amount), memo ?? "");
    console.log(`[PAY] ${amount} USDC -> ${recipient} | ${result.signature}`);
    res.json({ status: "confirmed", ...result });
  } catch (e) {
    console.error("[PAY:ERROR]", e);
    res.status(500).json({ status: "failed", error: String(e) });
  }
});

const port = Number(process.env.PORT ?? 3000);
app.listen(port, () => console.log(`payments service on :${port} (${process.env.SOLANA_NETWORK ?? "devnet"})`));
