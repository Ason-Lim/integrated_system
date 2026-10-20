import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import ChatWindow from "./ChatWindow"; // App 대신 ChatWindow를 불러옵니다.
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ChatWindow />
  </StrictMode>,
);