import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// 개발 서버: /api, /go 요청을 FastAPI(consumer, :8000)로 넘긴다.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const target = env.VITE_API_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target, changeOrigin: true },
        "/go": { target, changeOrigin: true },
      },
    },
  };
});
