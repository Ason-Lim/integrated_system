import { createContext, useContext } from "react";
import type { Candidate } from "../types/blocks";
import type { SendPayload } from "../state/useConversation";

export interface ChatActionsValue {
  send: (payload: SendPayload, userText?: string) => void;
  openDetail: (c: Candidate) => void;
  busy: boolean;
  sessionId: string | null;
}

export const ChatActions = createContext<ChatActionsValue>({
  send: () => {}, openDetail: () => {}, busy: false, sessionId: null,
});
export const useChatActions = () => useContext(ChatActions);
