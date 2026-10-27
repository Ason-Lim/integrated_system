import type { Block } from "../types/blocks";
import { Markdown } from "../lib/Markdown";
import { CandidateCompare } from "./CandidateCompare";
import { ChipsRow } from "./ChipsRow";
import { ClarifyForm } from "./ClarifyForm";
import { ComparisonCard } from "./ComparisonCard";
import { ProductList, SponsoredList } from "./ProductList";
import { ShippingOptions } from "./ShippingOptions";

/** blocks 배열을 순회하며 type 별 컴포넌트를 렌더링한다. 모르는 type 은 조용히 건너뛴다. */
export function BlockRenderer({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) => (
        <div key={i} className="rise" style={{ animationDelay: `${Math.min(i, 6) * 40}ms` }}>
          <BlockView block={b} />
        </div>
      ))}
    </>
  );
}

function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case "text":
      return <Markdown text={block.data.md ?? block.data.text ?? ""} className="my-1.5 space-y-1 text-[16.5px] leading-relaxed" />;
    case "notice":
      return (
        <Markdown text={block.data.md}
          className={`my-3 rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed ${block.data.affiliate ? "border border-line bg-surface text-ink" : block.data.tone === "warn" ? "bg-warnSoft text-warn" : "bg-chip text-ink2"}`} />
      );
    case "verdict":
      return <Markdown text={block.data.md} className="my-4 border-l-[3px] border-accent pl-3 text-[16.5px]" />;
    case "candidate_compare":
      return <CandidateCompare block={block} />;
    case "comparison_pair":
      return <ComparisonCard block={block} />;
    case "product_list":
      return <ProductList block={block} />;
    case "sponsored_list":
      return <SponsoredList block={block} />;
    case "clarify_form":
      return <ClarifyForm block={block} />;
    case "shipping_options":
      return <ShippingOptions block={block} />;
    case "chips":
      return <ChipsRow block={block} />;
    default:
      return null;
  }
}
