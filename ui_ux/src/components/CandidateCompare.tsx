import type { Candidate, CandidateCompareBlock } from "../types/blocks";
import { useChatActions } from "./ChatActions";
import { EvidenceTags, MallCheckNote, SourceMeta, Thumb, TotalPrice, UnverifiedTags } from "./ui";
import { cx, won } from "../lib/format";

/** 상품명 앞의 [빨간특기] 같은 대괄호 태그를 제거한다. */
function cleanTitle(title: string): string {
  return title.replace(/^\s*(\[[^\]]*\]\s*)+/, "").trim() || title;
}

/**
 * ③ 후보 비교 — 3개 내외 후보를 같은 기준(총가격·중량·배송·선택 이유·확인되지 않은 조건)으로 비교.
 * 세로 리스트 카드: 카드마다 안내 배지 → 썸네일·상품명·가격 → 미확인 태그 → 상세 보기.
 */
export function CandidateCompare({ block }: { block: CandidateCompareBlock }) {
  const { conditions, title } = block.data;
  const { openDetail } = useChatActions();
  // 동일 상품(제목+가격) 중복 제거
  const seen = new Set<string>();
  const candidates = block.data.candidates.filter((c) => {
    const key = `${c.title.trim()}::${c.total ?? c.price}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  if (!candidates.length) return null;

  const totals = candidates.map((c) => c.total).filter((v): v is number => v != null);
  const minTotal = totals.length ? Math.min(...totals) : null;
  const per = candidates.map((c) => c.per100g).filter((v): v is number => v != null);
  const minPer = per.length > 1 ? Math.min(...per) : null;

  const isBestTotal = (c: Candidate) => minTotal != null && c.total === minTotal && totals.length > 1;

  return (
    <section aria-label={title ?? "후보 비교"} className="my-3">
      {conditions?.length ? (
        <div className="mb-3 flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-ink3">적용한 조건</span>
          {conditions.map((c) => <span key={c} className="rounded-full border border-line bg-surface px-2.5 py-0.5">{c}</span>)}
        </div>
      ) : null}

      {/* ── 세로 리스트 카드 ── */}
      <div className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-chip px-2.5 py-1 text-[11px] font-medium text-ink3">
        참고용 후보 · 구매조건 근거가 부족해 순위 비교에서 분리했어요
      </div>
      <div className="space-y-4">
        {candidates.map((c) => (
          <article key={c.key} className="card rise p-5">
            <div className="flex gap-4">
              <Thumb c={c} />
              <div className="min-w-0 flex-1">
                <span className="text-xs font-bold text-accent">후보 {c.rank}</span>
                <button type="button" onClick={() => openDetail(c)}
                  className="line-clamp-2 block text-left text-base font-bold leading-snug hover:underline">{cleanTitle(c.title)}</button>
                <div className="mt-1.5"><TotalPrice c={c} best={isBestTotal(c)} /></div>
                <div className="mt-1 text-xs text-ink2">
                  {c.weightLabel ?? <span className="text-warn">중량 표기 없음</span>}
                  {c.per100g != null && <span className={cx("ml-1.5", c.per100g === minPer ? "font-semibold text-accent" : "")}>100g당 {won(c.per100g)}</span>}
                </div>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-1.5">
              {c.unverified.length > 0 && <UnverifiedTags items={c.unverified} compact />}
              <MallCheckNote c={c} />
            </div>

            {c.reasons.length > 0 && (
              <ul className="mt-3 space-y-0.5 border-t border-line pt-3 text-sm text-ink2">
                {c.reasons.map((r) => <li key={r} className="leading-snug">· {r}</li>)}
              </ul>
            )}

            <div className="mt-3 flex items-center justify-between gap-2">
              <SourceMeta c={c} />
              <button type="button" className="ghost-btn shrink-0" onClick={() => openDetail(c)}>상세·리뷰 근거 보기</button>
            </div>
          </article>
        ))}
      </div>

      {candidates.some((c) => c.evidence.length) && (
        <details className="mt-2 text-sm text-ink2">
          <summary className="cursor-pointer select-none py-1 text-ink3">확인된 근거 펼치기</summary>
          <div className="mt-2 space-y-2">
            {candidates.map((c) => (
              <div key={c.key} className="flex flex-wrap items-center gap-2">
                <span className="w-14 shrink-0 text-xs font-bold text-accent">후보 {c.rank}</span>
                <EvidenceTags items={c.evidence} />
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

