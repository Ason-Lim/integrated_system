# ui_ux — 소비자 대화형 추천 화면 (React + TypeScript + Tailwind)

첫 화면 → 조건 확인 → 후보 비교 → 상품 상세(+구매 연결 미리보기) 흐름. 설계: [docs/UI_UX_DESIGN.md](docs/UI_UX_DESIGN.md)

```bash
npm install
npm run dev:mock   # 백엔드 없이 예시 데이터로 (http://localhost:5173)
npm run dev        # 실제 API: 먼저 ../run_consumer.sh (FastAPI :8000)
npm run build      # 타입 검사 + dist/
```

예시 모드에서 “부모님 드릴 부드러운 소고기, 10만원 안쪽”을 누르면 전체 흐름(①~⑤)을, “두바이 쫀득쿠키”는 1:1 비교 카드를 볼 수 있습니다.
