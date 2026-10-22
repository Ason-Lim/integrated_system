import type { ChatRequest, ChatResponse } from "../types/blocks";
import { mockChat } from "./mock";
import { normalize } from "./adapt";

export const API_MODE: "mock" | "live" = import.meta.env.VITE_API_MODE === "mock" ? "mock" : "live";

/** POST /api/chat — consumer/app.py 의 ChatIn 과 같은 형식 */
export async function sendChat(req: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
  if (API_MODE === "mock") return normalize(await mockChat(req));
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(req.session_id ? { "x-session-id": req.session_id } : {}) },
    body: JSON.stringify(req),
    signal,
  });
  if (!r.ok) throw new Error(`chat ${r.status}`);
  return normalize(await r.json());
}

/** 판매처 이동 — 서버가 직전 추천 결과의 URL 로만 리다이렉트한다 (/go/{sid}/{rank}) */
export const goUrl = (sid: string | null, rank: number) => (sid ? `/go/${sid}/${rank}` : null);
