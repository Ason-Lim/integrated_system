import { Composer } from "./Composer";

const EXAMPLES = [
  { text: "부모님 드릴 부드러운 소고기, 10만원 안쪽", tag: "선물" },
  { text: "두바이 쫀득쿠키 2개만 비교해줘", tag: "간식" },
  { text: "소고기 미역국 끓이려는데 재료 뭐 사야 해?", tag: "레시피" },
  { text: "캠핑 가서 구워 먹을 고기 4인분", tag: "캠핑" },
];

/** ① 원하는 것 입력 — 자연어 한 문장 + 예시 질문 */
export function HomeScreen({ onSend, busy }: { onSend: (text: string) => void; busy: boolean }) {
  return (
    <section className="mx-auto flex min-h-[calc(100dvh-57px)] max-w-chat flex-col justify-center px-4 pb-16 pt-10">
      <p className="mb-3 text-sm font-semibold text-accent">장보기 도우미</p>
      <h1 className="text-[28px] font-extrabold leading-[1.3] tracking-tight sm:text-[34px]">
        누구에게, 무엇을, 얼마 안에서.<br />
        <span className="text-ink2">한 문장이면 충분해요.</span>
      </h1>
      <p className="mt-3 max-w-[34em] text-ink2">
        고르는 데 꼭 필요한 것만 몇 가지 여쭤본 뒤, 후보 3개를 총가격·중량·배송·근거로 나란히 보여 드려요.
      </p>

      <div className="mt-7">
        <Composer onSend={onSend} busy={busy} autoFocus large placeholder="예: 부모님 드릴 부드러운 소고기, 10만원 안쪽" />
      </div>

      <div className="mt-6">
        <p className="mb-2 text-xs font-semibold text-ink3">이렇게 물어보세요</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {EXAMPLES.map((e) => (
            <button key={e.text} type="button" disabled={busy} onClick={() => onSend(e.text)}
              className="group flex items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3 text-left transition hover:border-ink3">
              <span className="rounded-md bg-chip px-1.5 py-0.5 text-[11px] font-semibold text-ink2">{e.tag}</span>
              <span className="flex-1 text-[15px]">{e.text}</span>
              <span className="text-ink3 transition group-hover:translate-x-0.5">→</span>
            </button>
          ))}
        </div>
      </div>

      <p className="mt-8 text-xs leading-relaxed text-ink3">
        유료로 소개되는 상품은 일반 추천과 섞지 않고 ‘유료 소개’로 따로 표시해요.
      </p>
    </section>
  );
}
