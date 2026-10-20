import { Fragment, type ReactNode } from "react";

/**
 * 서버 문구용 최소 마크다운: **굵게**, 줄바꿈, "- " 목록.
 * HTML 을 해석하지 않으므로 (dangerouslySetInnerHTML 미사용) 주입 위험이 없다.
 */
function inline(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={i} className="font-bold">{part.slice(2, -2)}</strong>
      : <Fragment key={i}>{part}</Fragment>,
  );
}

/** "1. 2. 3. ..." 처럼 숫자만 무한히 이어붙은 비정상 문자열을 걸러낸다. */
function isNumericNoise(s: string): boolean {
  const tokens = s.trim().split(/\s+/);
  if (tokens.length < 5) return false;
  return tokens.every((t) => /^\d+\.?$/.test(t));
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  if (!text || isNumericNoise(text)) return null;
  const lines = text.split("\n");
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (!list.length) return;
    out.push(
      <ul key={`ul${out.length}`} className="my-1.5 space-y-1 pl-4">
        {list.map((l, i) => (
          <li key={i} className={l.startsWith("  ") ? "ml-3 list-none text-ink2" : "list-disc"}>{inline(l.trim())}</li>
        ))}
      </ul>,
    );
    list = [];
  };
  lines.forEach((raw, i) => {
    const m = raw.match(/^(\s*)- (.*)$/);
    if (m) { list.push(m[1] + m[2]); return; }
    flush();
    if (raw.trim()) out.push(<p key={i}>{inline(raw)}</p>);
  });
  flush();
  return <div className={className}>{out}</div>;
}
