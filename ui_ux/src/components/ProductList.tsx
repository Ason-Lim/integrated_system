import type { Candidate, ProductListBlock, SponsoredListBlock } from "../types/blocks";
import { cardToCandidate } from "../api/adapt";
import { useChatActions } from "./ChatActions";
import { SourceMeta, Thumb, TotalPrice, UnverifiedTags } from "./ui";

function Row({ c, sponsored }: { c: Candidate; sponsored?: boolean }) {
  const { openDetail } = useChatActions();
  return (
    <article className="flex gap-3 p-4">
      <Thumb c={c} size="sm" />
      <div className="min-w-0 flex-1 space-y-1.5">
        <button type="button" onClick={() => openDetail(c)} className="block text-left font-bold leading-snug hover:underline">
          {sponsored && <span className="tag mr-1.5 bg-sponsorSoft align-middle text-sponsor">유료 소개</span>}
          {c.title}
        </button>
        <TotalPrice c={c} />
        {!sponsored && c.reasons[0] && <p className="text-sm text-ink2">{c.reasons[0]}</p>}
        <UnverifiedTags items={c.unverified} compact />
        <SourceMeta c={c} />
      </div>
    </article>
  );
}

/** product_list — 후보가 1~2개이거나, 순위 비교에서 분리된 참고용 목록 */
export function ProductList({ block }: { block: ProductListBlock }) {
  const reference = block.data.items.every((c) => c.rankable === false);
  return (
    <div className="card my-3 divide-y divide-line">
      {reference && (
        <p className="px-4 py-2.5 text-xs font-semibold text-warn">
          참고용 후보 · 구매조건 근거가 부족해 순위 비교에서 분리했어요
        </p>
      )}
      {block.data.items.map((it) => <Row key={`${it.rank}-${it.title}`} c={cardToCandidate(it)} />)}
    </div>
  );
}

/** 유료 소개 — 일반 추천과 분리된 별도 영역. 색·라벨·위치 모두 구분한다. */
export function SponsoredList({ block }: { block: SponsoredListBlock }) {
  return (
    <section aria-label="유료 소개" className="my-4 rounded-card border border-dashed border-sponsor/40 bg-sponsorSoft/40">
      <header className="flex flex-wrap items-baseline gap-2 px-4 pt-3">
        <h3 className="text-sm font-bold text-sponsor">유료 소개</h3>
        <p className="text-xs text-ink2">{block.data.note ?? "판매처가 비용을 내고 소개하는 상품이에요. 추천 순위에 반영하지 않아요."}</p>
      </header>
      <div className="divide-y divide-line">
        {block.data.items.map((c) => <Row key={c.key} c={c} sponsored />)}
      </div>
    </section>
  );
}
