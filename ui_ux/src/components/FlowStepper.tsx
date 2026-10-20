import type { FlowStep } from "../state/useConversation";
import { cx } from "../lib/format";

const STEPS: { n: FlowStep; label: string }[] = [
  { n: 1, label: "원하는 것" },
  { n: 2, label: "조건 확인" },
  { n: 3, label: "후보 비교" },
  { n: 4, label: "상품 판단" },
  { n: 5, label: "구매 연결" },
];

/** 지금 어느 단계인지 보여 주는 진행 표시. 모바일에서는 현재 단계 이름만 보인다. */
export function FlowStepper({ step }: { step: FlowStep }) {
  return (
    <ol className="flex items-center gap-1" aria-label="진행 단계">
      {STEPS.map((s, i) => {
        const state = s.n < step ? "done" : s.n === step ? "now" : "todo";
        return (
          <li key={s.n} className="flex items-center gap-1" aria-current={state === "now" ? "step" : undefined}>
            {i > 0 && <span className={cx("hidden h-px w-2 min-[420px]:block sm:w-4", s.n <= step ? "bg-ink" : "bg-line")} aria-hidden />}
            <span className={cx("grid h-6 w-6 place-items-center rounded-full text-[11px] font-bold tabular-nums",
              state === "now" ? "bg-ink text-surface" : state === "done" ? "bg-accentSoft text-accent" : "bg-chip text-ink3")}>
              {state === "done" ? "✓" : s.n}
            </span>
            <span className={cx("whitespace-nowrap text-xs", state === "now" ? "font-bold" : "hidden text-ink3 lg:inline")}>{s.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
