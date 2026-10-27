/**
 * 백엔드 응답 → 화면 블록 정규화.
 *
 * 1) 같은 블록의 형식 차이를 흡수한다 (text.md / text.text, chips 문자열 / 객체 …)
 * 2) 주 추천 결과(카드 3장 이상)는 ③ 후보 비교(candidate_compare)로 묶는다.
 *    카드 2장짜리 comparison_pair(후속 1:1 비교)는 split view 그대로 둔다.
 * 3) is_sponsored 카드는 일반 추천에서 빼서 sponsored_list 로 분리한다.
 */
import type {
  ApiCard, Block, Candidate, ChatResponse, ChipItem, ClarifyFormBlock, ClarifyQuestion,
} from "../types/blocks";
import { parseWeightFromTitle, per100g, weightLabel, won } from "../lib/format";

export const toChip = (c: string | ChipItem): ChipItem => (typeof c === "string" ? { label: c } : c);

export function cardToCandidate(c: ApiCard): Candidate {
  const ship = c.shipping_fee ?? null;
  const total = c.total ?? (ship != null ? c.price + ship : null);
  const g = c.weight_g ?? parseWeightFromTitle(c.title);
  const reasons = [c.reasoning || c.reason].filter((x): x is string => !!x);
  return {
    rank: c.rank,
    key: `${c.mall ?? "m"}:${c.pid ?? c.title}`,
    title: c.title,
    image: c.image ?? c.image_url ?? null,
    source: c.source ?? c.mall ?? "판매처",
    mall: c.mall,
    price: c.price,
    shippingFee: ship,
    total,
    weightLabel: weightLabel(g),
    per100g: per100g(total, g),
    unitLabel: c.unit_price && c.unit_count ? `${c.unit_count}개 · 개당 약 ${won(c.unit_price)}` : null,
    delivery: c.delivery_terms ? { label: c.delivery_terms, verified: true } : null,
    reasons,
    evidence: c.evidence ?? [],
    unverified: [
      ...(c.unverified ?? []),
      ...(ship == null ? ["배송비"] : []),
      // 도착 예정일은 판매처 API가 주지 않는 경우가 많아 '미확인' 경고 대신 카드의 안내 문구로 보여준다
      ...(c.delivery_terms || c.check_at_mall ? [] : ["도착 예정일"]),
    ].filter((v, i, a) => a.indexOf(v) === i),
    badges: c.badges ?? [],
    observed: c.observed,
    stale: c.stale,
    url: c.url,
    isSample: c.is_sample,
    isSponsored: c.is_sponsored,
    affiliate: c.affiliate,
    affiliateProgram: c.affiliate_program,
    checkAtMall: c.check_at_mall,
    deliveryHint: c.delivery_hint,
    followUp: c.follow_up,
    detail: c.detail ?? {
      sellerFacts: [
        ...(c.spec ? [{ label: "규격", value: c.spec, source: { label: c.source ?? "판매처", url: c.url } }] : []),
        { label: "상품가", value: won(c.price), source: { label: c.source ?? "판매처", url: c.url } },
        { label: "배송비", value: ship == null ? "판매자 표기 확인 필요" : won(ship), source: { label: c.source ?? "판매처", url: c.url } },
      ],
      reviews: null,
      notes: ["리뷰 요약은 상품 상세 API 연결 후 표시됩니다."],
    },
  };
}

function normalizeClarify(b: ClarifyFormBlock): ClarifyFormBlock {
  const d = b.data;
  let questions: ClarifyQuestion[] = d.questions ?? [];
  if (!questions.length && d.title && d.options) {
    questions = [{ id: "budget", label: d.title, options: d.options }];
  }
  return { type: "clarify_form", data: { ...d, questions, layout: d.layout ?? "sequential" } };
}

export function normalize(res: ChatResponse): ChatResponse {
  const out: Block[] = [];
  const sponsored: Candidate[] = [];
  const seen = new Set<string>();
  const cardKey = (c: ApiCard) => `${c.mall ?? ""}:${c.pid ?? c.title}`;

  for (const b of res.blocks) {
    switch (b.type) {
      case "text":
        out.push({ type: "text", data: { md: b.data.md ?? b.data.text ?? "" } });
        break;
      case "chips":
        out.push({ type: "chips", data: { mode: b.data.mode ?? "message", items: b.data.items.map(toChip) } });
        break;
      case "clarify_form":
        out.push(normalizeClarify(b));
        break;
      case "comparison_pair": {
        const cards = b.data.pairs.flatMap((p) => p.cards);
        const general = cards.filter((c) => !c.is_sponsored);
        general.forEach((c) => seen.add(cardKey(c)));
        sponsored.push(...cards.filter((c) => c.is_sponsored).map(cardToCandidate));
        if (general.length >= 3) {
          out.push({ type: "candidate_compare", data: { candidates: general.map(cardToCandidate) } });
        } else if (general.length) {
          out.push({ type: "comparison_pair", data: { pairs: [{ pair_index: 0, cards: general, compare: general.length === 2, chips: b.data.pairs[0]?.chips }] } });
        }
        break;
      }
      case "product_list": {
        // 같은 응답 안에서 이미 보여 준 카드는 다시 그리지 않는다
        // (presenter 가 rankable 후보가 0개일 때 같은 목록을 두 번 내려주는 경우 대응)
        const general = b.data.items.filter((c) => !c.is_sponsored && !seen.has(cardKey(c)));
        sponsored.push(...b.data.items.filter((c) => c.is_sponsored).map(cardToCandidate));
        general.forEach((c) => seen.add(cardKey(c)));
        if (general.length) out.push({ type: "product_list", data: { ...b.data, items: general } });
        break;
      }
      case "candidate_compare": {
        const general = b.data.candidates.filter((c) => !c.isSponsored);
        sponsored.push(...b.data.candidates.filter((c) => c.isSponsored));
        out.push({ type: "candidate_compare", data: { ...b.data, candidates: general } });
        break;
      }
      case "sponsored_list":
        sponsored.push(...b.data.items);
        break;
      default:
        out.push(b);
    }
  }
  if (sponsored.length) {
    // 유료 소개는 항상 일반 추천 '뒤', 별도 영역
    const at = out.findIndex((b) => b.type === "chips");
    const block: Block = { type: "sponsored_list", data: { items: sponsored.map((s) => ({ ...s, isSponsored: true })) } };
    if (at >= 0) out.splice(at, 0, block); else out.push(block);
  }
  return { ...res, blocks: out };
}
