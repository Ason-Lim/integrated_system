export const isDemo = import.meta.env.VITE_DATA_MODE !== 'api';

export async function sendMessage(
  message: string,
  sessionId: string | null,
  signal: AbortSignal
): Promise<any> {
  // 1. 데모 모드일 경우 (가짜 응답)
  if (isDemo) {
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve({
          session_id: sessionId ?? "demo-session",
          blocks: [
            {
              type: "text",
              data: { text: `"${message}"에 대한 데모 응답입니다. 실제 추천 결과를 보시려면 .env 파일에 VITE_DATA_MODE=api 를 설정해 주세요.` }
            }
          ]
        });
      }, 1000);
    });
  }

  // 2. 실제 API 모드일 경우 (FastAPI 백엔드 호출)
  const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');
  const endpoint = import.meta.env.VITE_CHAT_ENDPOINT ?? '/api/chat';

  const response = await fetch(`${base}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });

  if (!response.ok) {
    throw new Error(`요청 실패 (${response.status}). 서버 연결을 확인해 주세요.`);
  }

  // parseResponse 없이 바로 JSON 데이터를 반환합니다.
  return await response.json();
}