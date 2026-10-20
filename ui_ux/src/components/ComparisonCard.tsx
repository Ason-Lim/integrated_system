import type { ApiCard, ComparisonPairBlock } from "../types/blocks";
import { useChatActions } from "./ChatActions";
import { cardToCandidate } from "../api/adapt";
import { SourceMeta, Thumb, TotalPrice, UnverifiedTags } from "./ui";
import { ChipButton } from "./ChipsRow";

/**
 * comparison_pair — 카드 1장 안에 상품 2개를 나란히(split view).
 * 모바일에서는 세로로 쌓인다. 각 상품 하단에 추천 이유(reasoning)와 후속 질문(follow_up).
 */
export function ComparisonCard({ block }: { block: ComparisonPairBlock }) {
  return (
    <div className="my-3 space-y-3">
      {block.data.pairs.map((pair) => (
        <section key={pair.pair_index} className="card overflow-hidden" aria-label="두 상품 비교">
          <div className="grid grid-cols-1 sm:grid-cols-2">
            {pair.cards.map((c, i) => (
              <PairSide key={`${c.rank}-${c.title}`} c={c} divider={i === 1} />
            ))}
          </div>
          {!!pair.chips?.length && (
            <div className="flex flex-wrap gap-2 border-t border-line bg-paper/60 px-4 py-3">
              {pair.chips.map((ch) => <ChipButton key={ch.label} item={ch} mode="message" />)}
            </div>
          )}
        </section>
      ))}
    </div>
  );
}

function PairSide({ c, divider }: { c: ApiCard; divider: boolean }) {
  const { openDetail } = useChatActions();
  const cand = cardToCandidate(c);
  return (
    <article className={`flex flex-col gap-3 p-4 ${divider ? "border-t border-line sm:border-l sm:border-t-0" : ""}`}>
      <div className="flex gap-3">
        <Thumb c={cand} />
        <div className="min-w-0">
          <span className="text-xs font-bold text-accent">{c.rank}위</span>
          <button type="button" onClick={() => openDetail(cand)} className="block text-left font-bold leading-snug hover:underline">
            {c.title}
          </button>
        </div>
      </div>
      <TotalPrice c={cand} />
      {(c.reasoning || c.reason) && (
        <p className="rounded-xl bg-chip px-3 py-2 text-sm leading-relaxed text-ink2">
          <span className="mr-1 font-semibold text-ink">추천 이유</span>{c.reasoning || c.reason}
        </p>
      )}
      <UnverifiedTags items={cand.unverified} />
      <SourceMeta c={cand} />
      {!!c.follow_up?.length && (
        <div className="mt-auto flex flex-wrap gap-1.5 pt-1">
          {c.follow_up.map((f) => <ChipButton key={f.label} item={f} mode="message" small />)}
        </div>
      )}
    </article>
  );
}
