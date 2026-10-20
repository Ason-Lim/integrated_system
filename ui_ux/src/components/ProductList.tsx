import type { Candidate, ProductListBlock, SponsoredListBlock } from "../types/blocks";
import { cardToCandidate } from "../api/adapt";
import { useChatActions } from "./ChatActions";
import { SourceMeta, Thumb, TotalPrice, UnverifiedTags } from "./ui";

/** 상품명 앞의 [빨간특기] 같은 대괄호 태그를 분리한다. */
function splitTitle(title: string): { tags: string[]; name: string } {
  const tags: string[] = [];
  const name = title.replace(/^\s*(\[([^\]]*)\]\s*)+/, (_, __, inner) => {
    return "";
  });
  const matches = title.match(/\[([^\]]*)\]/g) ?? [];
  for (const m of matches) tags.push(m.slice(1, -1).trim());
  return { tags, name: name.trim() || title };
}

function Row({ c, sponsored }: { c: Candidate; sponsored?: boolean }) {
  const { openDetail } = useChatActions();
  const { tags, name } = splitTitle(c.title);
  return (
    <article className="flex gap-4 p-4">
      <Thumb c={c} />
      <div className="min-w-0 flex-1 space-y-1.5">
        {(sponsored || tags.length > 0) && (
          <div className="flex flex-wrap gap-1">
            {sponsored && <span className="tag bg-sponsorSoft text-sponsor">유료 소개</span>}
            {tags.map((t) => <span key={t} className="tag bg-chip text-ink2">{t}</span>)}
          </div>
        )}
        <button type="button" onClick={() => openDetail(c)}
          className="line-clamp-2 block text-left font-bold leading-snug hover:underline">
          {name}
        </button>
        <TotalPrice c={c} size="lg" />
        {!sponsored && c.reasons[0] && <p className="text-sm text-ink2">{c.reasons[0]}</p>}
        <div className="flex flex-wrap gap-1.5">
          <span className="rounded-md bg-yellow-50 px-2 py-1 text-xs text-yellow-700">? 평점 미확인</span>
          <span className="rounded-md bg-yellow-50 px-2 py-1 text-xs text-yellow-700">? 후기 수 미확인</span>
          <span className="rounded-md bg-yellow-50 px-2 py-1 text-xs text-yellow-700">? 도착 예정일 미확인</span>
          <UnverifiedTags items={c.unverified} compact />
        </div>
        <SourceMeta c={c} />
      </div>
    </article>
  );
}

/** product_list — 후보가 1~2개이거나, 순위 비교에서 분리된 참고용 목록 */
export function ProductList({ block }: { block: ProductListBlock }) {
  const reference = block.data.items.every((c) => c.rankable === false);
  // 제목 기준 중복 제거
  const seen = new Set<string>();
  const items = block.data.items.filter((it) => {
    const key = it.title.trim();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return (
    <div className="card my-3 divide-y divide-line">
      {reference && (
        <p className="px-4 py-2.5 text-xs font-semibold text-warn">
          참고용 후보 · 구매조건 근거가 부족해 순위 비교에서 분리했어요
        </p>
      )}
      {items.map((it) => <Row key={`${it.rank}-${it.title}`} c={cardToCandidate(it)} />)}
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
        {(() => {
          const seen = new Set<string>();
          return block.data.items.filter((c) => {
            const key = c.title.trim();
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          }).map((c) => <Row key={c.key} c={c} sponsored />);
        })()}
      </div>
    </section>
  );
}
