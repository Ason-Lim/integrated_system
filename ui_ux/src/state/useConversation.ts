import { useCallback, useMemo, useRef, useState } from "react";
import type { Block, Candidate, ChatRequest } from "../types/blocks";
import { sendChat } from "../api/client";

export interface Turn {
  id: number;
  role: "user" | "bot";
  text?: string;
  blocks?: Block[];
  pending?: boolean;
  error?: string;
}

/** 화면 흐름 단계: ① 입력 ② 조건 ③ 비교 ④ 상세 ⑤ 구매 */
export type FlowStep = 1 | 2 | 3 | 4 | 5;

export type SendPayload = Omit<ChatRequest, "session_id">;

export function useConversation() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<Candidate | null>(null);
  const [purchasing, setPurchasing] = useState(false);
  const seq = useRef(0);
  const sidRef = useRef<string | null>(null);

  const send = useCallback(async (payload: SendPayload, userText?: string) => {
    const uid = ++seq.current, bid = ++seq.current;
    setTurns((t) => [
      ...t,
      ...(userText ? [{ id: uid, role: "user" as const, text: userText }] : []),
      { id: bid, role: "bot", pending: true },
    ]);
    setBusy(true);
    try {
      const res = await sendChat({ session_id: sidRef.current, ...payload });
      sidRef.current = res.session_id;
      setSessionId(res.session_id);
      setTurns((t) => t.map((x) => (x.id === bid ? { id: bid, role: "bot", blocks: res.blocks } : x)));
    } catch {
      setTurns((t) => t.map((x) => (x.id === bid ? { id: bid, role: "bot", error: "연결에 문제가 있어요. 잠시 후 다시 시도해 주세요." } : x)));
    } finally {
      setBusy(false);
    }
  }, []);

  const reset = useCallback(() => {
    sidRef.current = null;
    setSessionId(null);
    setTurns([]);
    setDetail(null);
    setPurchasing(false);
  }, []);

  const openDetail = useCallback((c: Candidate | null) => { setDetail(c); setPurchasing(false); }, []);

  const step: FlowStep = useMemo(() => {
    if (detail) return purchasing ? 5 : 4;
    const lastBot = [...turns].reverse().find((t) => t.role === "bot" && t.blocks);
    if (!turns.length) return 1;
    const types = new Set(lastBot?.blocks?.map((b) => b.type));
    if (types.has("candidate_compare") || types.has("comparison_pair") || types.has("product_list")) return 3;
    if (types.has("clarify_form")) return 2;
    return 1;
  }, [turns, detail, purchasing]);

  return { turns, sessionId, busy, send, reset, detail, openDetail, purchasing, setPurchasing, step };
}
