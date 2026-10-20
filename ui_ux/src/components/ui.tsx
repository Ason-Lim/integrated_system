/** 작은 공용 조각: 썸네일 · 가격 · 근거/미확인 태그 · 출처 */
import { useState } from "react";
import type { Candidate } from "../types/blocks";
import { cx, won } from "../lib/format";

export function Thumb({ c, size = "md" }: { c: Pick<Candidate, "image" | "title">; size?: "sm" | "md" | "lg" }) {
  const [failed, setFailed] = useState(false);
  const dim = size === "sm" ? "h-14 w-14 text-lg" : size === "lg" ? "h-28 w-28 text-3xl" : "h-20 w-20 text-2xl";
  const initial = (c.title.match(/[가-힣A-Za-z]/)?.[0] ?? "·");
  return (
    <div className={cx("grid shrink-0 place-items-center overflow-hidden rounded-2xl bg-chip font-extrabold text-ink3", dim)}>
      {c.image && !failed
        ? <img src={c.image} alt="" loading="lazy" onError={() => setFailed(true)} className="h-full w-full rounded-xl object-cover" />
        : initial}
    </div>
  );
}

/** 총가격 = 배송비 포함. 배송비를 모르면 '확정 불가'로 보여 준다 (0원으로 가정하지 않음) */
export function TotalPrice({ c, best, size = "md" }: { c: Candidate; best?: boolean; size?: "md" | "lg" }) {
  return (
    <div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-xs text-ink3">{c.total == null ? "상품가" : "총가격"}</span>
        <span className={cx("font-extrabold tracking-tight", size === "lg" ? "text-2xl" : "text-xl", best && "text-accent")}>
          {won(c.total ?? c.price)}
        </span>
        {best && <span className="tag bg-accentSoft text-accent">최저</span>}
      </div>
      <div className="text-xs text-ink2">
        {c.shippingFee == null
          ? <>상품가 {won(c.price)} + <b className="font-semibold text-warn">배송비 미확인</b></>
          : c.shippingFee === 0 ? <>무료배송 포함</> : <>상품가 {won(c.price)} + 배송비 {won(c.shippingFee)}</>}
      </div>
    </div>
  );
}

export function EvidenceTags({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((x) => <span key={x} className="tag bg-chip text-ink2">✓ {x}</span>)}
    </div>
  );
}

export function UnverifiedTags({ items, compact }: { items: string[]; compact?: boolean }) {
  if (!items.length) return <span className="text-xs text-ink3">확인되지 않은 조건 없음</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((x) => (
        <span key={x} className="tag bg-warnSoft text-warn" title="판매자 표기나 리뷰로 확인되지 않았어요">
          ? {x}{compact ? "" : " 미확인"}
        </span>
      ))}
    </div>
  );
}

export function SourceMeta({ c }: { c: Candidate }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-ink3">
      <span className="inline-flex items-center gap-1.5 rounded-full bg-chip px-2.5 py-0.5 text-ink2">
        <i className={cx("inline-block h-2 w-2 rounded-full", c.mall === "naver" ? "bg-[#03c75a]" : c.mall === "coupang" ? "bg-[#e4312b]" : "bg-ink3")} />
        {c.source}
      </span>
      {c.observed && <span className={cx(c.stale && "font-semibold text-warn")}>{c.observed}{c.stale ? " · 다시 확인 필요" : ""}</span>}
      {c.isSample && <span className="tag bg-warnSoft text-warn">예시 데이터</span>}
    </div>
  );
}
