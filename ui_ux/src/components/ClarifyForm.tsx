import { useState } from "react";
import type { ClarifyFormBlock, ClarifyQuestion } from "../types/blocks";
import { useChatActions } from "./ChatActions";
import { cx } from "../lib/format";

/**
 * ② 필요한 조건 확인 — 선택에 영향을 주는 질문만, 한 번에 하나씩.
 * 마지막 질문까지 고르면(또는 건너뛰면) answers 를 한 번에 서버로 보낸다 (ChatIn.answers).
 */
export function ClarifyForm({ block }: { block: ClarifyFormBlock }) {
  const { send, busy } = useChatActions();
  const qs: ClarifyQuestion[] = block.data.questions ?? [];
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, { value: string; label: string } | null>>({});
  const [done, setDone] = useState(false);

  if (!qs.length) return null;
  const sequential = block.data.layout !== "stacked";
  const finished = idx >= qs.length;

  const choose = (q: ClarifyQuestion, value: string | null, label: string) => {
    setAnswers((a) => ({ ...a, [q.id]: value == null ? null : { value, label } }));
    if (sequential) setIdx((i) => Math.max(i, qs.indexOf(q) + 1));
  };

  const submit = () => {
    const payload: Record<string, string> = {};
    const labels: string[] = [];
    for (const q of qs) {
      const a = answers[q.id];
      if (a) { payload[q.id] = a.value; labels.push(a.label); }
    }
    setDone(true);
    send({ answers: payload }, labels.length ? labels.join(" · ") : "조건 없이 볼게요");
  };

  const answeredCount = qs.filter((q) => q.id in answers).length;
  const visible = sequential ? qs.slice(0, Math.min(idx + 1, qs.length)) : qs;

  return (
    <section aria-label="조건 확인" className={cx("card my-3 p-4 sm:p-5", done && "opacity-60")}>
      {sequential && qs.length > 1 && (
        <div className="mb-4 flex items-center gap-3">
          <div className="flex flex-1 gap-1" aria-hidden>
            {qs.map((q, i) => (
              <span key={q.id} className={cx("h-1 flex-1 rounded-full", i < answeredCount ? "bg-ink" : i === idx ? "bg-ink3" : "bg-line")} />
            ))}
          </div>
          <span className="text-xs tabular-nums text-ink3">{Math.min(answeredCount + (finished ? 0 : 1), qs.length)}/{qs.length}</span>
        </div>
      )}

      <div className="space-y-5">
        {visible.map((q, qi) => {
          const a = answers[q.id];
          const isCurrent = !sequential || qi === idx;
          // 지난 질문은 한 줄 요약으로 접고, 누르면 다시 고칠 수 있다
          if (sequential && !isCurrent && q.id in answers) {
            return (
              <button key={q.id} type="button" disabled={done}
                onClick={() => setIdx(qi)}
                className="flex w-full items-center justify-between gap-3 rounded-xl bg-chip px-3.5 py-2.5 text-left text-sm">
                <span className="text-ink2">{q.label}</span>
                <span className="font-semibold">{a ? a.label : "건너뜀"} <span className="ml-1 text-ink3">수정</span></span>
              </button>
            );
          }
          return (
            <fieldset key={q.id} className="rise" disabled={done}>
              <legend className="text-[17px] font-bold leading-snug">{q.label}</legend>
              {q.why && <p className="mt-0.5 text-sm text-ink3">{q.why}</p>}
              <div role="radiogroup" aria-label={q.label} className="mt-3 grid grid-cols-1 gap-2 min-[420px]:grid-cols-3">
                {q.options.map((o) => {
                  const on = a?.value === o.value;
                  return (
                    <button key={o.value} type="button" role="radio" aria-checked={on}
                      onClick={() => choose(q, o.value, o.label)}
                      className={cx("flex flex-col items-start rounded-2xl border-[1.5px] px-4 py-3 text-left transition",
                        on ? "border-ink bg-ink text-surface" : "border-line bg-surface hover:border-ink3")}>
                      <span className="font-semibold">{o.label}</span>
                      {o.hint && <span className={cx("text-xs", on ? "text-surface/70" : "text-ink3")}>{o.hint}</span>}
                    </button>
                  );
                })}
              </div>
              {q.skippable !== false && sequential && (
                <button type="button" onClick={() => choose(q, null, "건너뜀")}
                  className="mt-2 text-sm text-ink3 underline-offset-2 hover:underline">
                  잘 모르겠어요 · 건너뛰기
                </button>
              )}
            </fieldset>
          );
        })}
      </div>

      {(!sequential || finished) && (
        <button type="button" className="primary-btn mt-5 w-full" disabled={busy || done || (!sequential && !answeredCount)} onClick={submit}>
          {done ? "조건을 보냈어요" : `${block.data.submit ?? "이 조건으로 다시 추천받기"} →`}
        </button>
      )}
    </section>
  );
}
