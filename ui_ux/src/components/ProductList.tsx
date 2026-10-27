import type { Candidate, ProductListBlock, SponsoredListBlock } from "../types/blocks";
import { cardToCandidate } from "../api/adapt";
import { cx } from "../lib/format";
import { useChatActions } from "./ChatActions";
import { MallCheckNote, SourceMeta, Thumb, TotalPrice, UnverifiedTags } from "./ui";

/** 상품명 속 [빨간특가] 같은 대괄호 태그를 분리한다. */
function splitTitle(title: string): { tags: string[]; name: string } {
  const tags = (title.match(/\[([^\]]*)\]/g) ?? []).map((m) => m.slice(1, -1).trim()).filter(Boolean);
  const name = title.replace(/\[[^\]]*\]\s*/g, "").trim();
  return { tags: [...new Set(tags)], name: name || title };
}

/** 제목 기준 중복 제거 */
function uniqueByTitle<T extends { title: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((it) => {
    const key = it.title.trim();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** 세로로 쌓이는 개별 상품 카드 — 썸네일 왼쪽, 정보 오른쪽 */
function ProductCard({ c, sponsored }: { c: Candidate; sponsored?: boolean }) {
  const { openDetail } = useChatActions();
  const { tags, name } = splitTitle(c.title);
  // 미확인 태그는 실제 데이터(c.unverified)에서만, 중복 없이 표시
  const unverified = [...new Set(c.unverified)];
  return (
    <article
      className={cx(
        "flex items-start gap-4 rounded-2xl border bg-surface p-4 transition hover:shadow-card",
        sponsored ? "border-dashed border-sponsor/40" : "border-line hover:border-accent/40",
      )}
    >
      <button type="button" onClick={() => openDetail(c)} aria-label={`${name} 상세 보기`} className="shrink-0">
        <Thumb c={c} />
      </button>
      <div className="min-w-0 flex-1 space-y-2">
        {(sponsored || c.affiliate || tags.length > 0) && (
          <div className="flex flex-wrap gap-1">
            {sponsored && <span className="tag bg-sponsorSoft text-sponsor">유료 소개</span>}
            {!sponsored && c.affiliate && (
              <span className="tag bg-chip text-ink2" title={`${c.affiliateProgram ?? "제휴"} 링크 — 구매 시 일정액의 수수료를 제공받습니다`}>
                제휴 링크 · 수수료 제공
              </span>
            )}
            {tags.map((t) => <span key={t} className="tag bg-chip text-ink2">{t}</span>)}
          </div>
        )}
        <button type="button" onClick={() => openDetail(c)}
          className="line-clamp-2 block text-left text-base font-bold leading-snug hover:underline">
          {name}
        </button>
        <TotalPrice c={c} size="lg" />
        {!sponsored && c.reasons[0] && <p className="text-sm leading-relaxed text-ink2">{c.reasons[0]}</p>}
        {unverified.length > 0 && <UnverifiedTags items={unverified} compact />}
        <MallCheckNote c={c} />
        <SourceMeta c={c} />
      </div>
    </article>
  );
}

/** product_list — 후보가 1~2개이거나, 순위 비교에서 분리된 참고용 목록 */
export function ProductList({ block }: { block: ProductListBlock }) {
  const items = uniqueByTitle(block.data.items);
  if (!items.length) return null;
  const reference = items.every((c) => c.rankable === false);
  return (
    <section className="my-3 flex flex-col gap-3">
      {/* 자세한 사유·가격 기준 안내는 서버가 notice 블록으로 함께 내려준다 */}
      {reference && <p className="text-xs font-semibold text-warn">참고용 후보</p>}
      {items.map((it) => <ProductCard key={`${it.rank}-${it.title}`} c={cardToCandidate(it)} />)}
    </section>
  );
}

/** 유료 소개 — 일반 추천과 분리된 별도 영역. 색·라벨·위치 모두 구분한다. */
export function SponsoredList({ block }: { block: SponsoredListBlock }) {
  const items = uniqueByTitle(block.data.items);
  if (!items.length) return null;
  return (
    <section aria-label="유료 소개" className="my-4 flex flex-col gap-3 rounded-card bg-sponsorSoft/40 p-3">
      <header className="flex flex-wrap items-baseline gap-2 px-1">
        <h3 className="text-sm font-bold text-sponsor">유료 소개</h3>
        <p className="text-xs text-ink2">{block.data.note ?? "판매처가 비용을 내고 소개하는 상품이에요. 추천 순위에 반영하지 않아요."}</p>
      </header>
      {items.map((c) => <ProductCard key={c.key} c={c} sponsored />)}
    </section>
  );
}
