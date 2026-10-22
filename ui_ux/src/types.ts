/** 채팅 화면(ChatWindow)용 메시지 모델 — 블록 계약은 types/blocks.ts 를 따른다. */
import type { Block } from "./types/blocks";

export interface Message {
  id: string;
  role: "user" | "assistant";
  text?: string;
  blocks?: Block[];
}
