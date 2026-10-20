import { useState } from "react";
import { cx } from "../lib/format";

interface Props {
  onSend: (text: string) => void;
  busy?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
  large?: boolean;
}

/** 하단 입력창 (첫 화면에서는 크게) */
export function Composer({ onSend, busy, placeholder = "조건을 바꾸거나 더 물어보세요", autoFocus, large }: Props) {
  const [v, setV] = useState("");
  const submit = () => {
    const t = v.trim();
    if (!t || busy) return;
    setV("");
    onSend(t);
  };
  return (
    <form onSubmit={(e) => { e.preventDefault(); submit(); }}
      className={cx("flex items-end gap-2 rounded-[26px] border border-line bg-surface shadow-card transition focus-within:border-ink3",
        large ? "p-2 pl-5" : "p-1.5 pl-4")}>
      <textarea
        value={v} rows={1} maxLength={500} autoFocus={autoFocus} aria-label="메시지"
        placeholder={placeholder}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
        }}
        className={cx("max-h-40 min-w-0 flex-1 resize-none bg-transparent outline-none placeholder:text-ink3",
          large ? "py-2.5 text-[17px]" : "py-2 text-base")}
      />
      <button type="submit" aria-label="보내기" disabled={busy || !v.trim()}
        className={cx("grid shrink-0 place-items-center rounded-full bg-ink text-surface transition disabled:opacity-25",
          large ? "h-11 w-11 text-lg" : "h-10 w-10")}>
        ↑
      </button>
    </form>
  );
}
