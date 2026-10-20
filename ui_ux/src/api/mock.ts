/**
 * 백엔드 없이 화면 흐름을 눌러 보기 위한 예시 시나리오.
 * 상품명·가격·리뷰는 모두 가상의 예시 데이터이며 화면에 '예시 데이터'로 표시된다.
 */
import type { Block, Candidate, ChatRequest, ChatResponse, ClarifyQuestion } from "../types/blocks";

type Topic = "beef" | "cookie" | "recipe" | null;
interface MockSession { topic: Topic; answered: boolean; answers: Record<string, string> }
const sessions = new Map<string, MockSession>();

const SAMPLE_SRC = { label: "예시몰 상품 상세 (예시)", url: null };

/* ───────── 소고기 시나리오 ───────── */

const BEEF_QUESTIONS: ClarifyQuestion[] = [
  {
    id: "servings", label: "몇 분이 드시나요?", why: "드실 인원에 따라 필요한 중량이 달라져요.",
    options: [
      { label: "2명", value: "2", hint: "600g 안팎" },
      { label: "3~4명", value: "3-4", hint: "1kg 안팎" },
      { label: "5명 이상", value: "5+", hint: "1.5kg 이상" },
    ],
  },
  {
    id: "cooking", label: "어떻게 드실 예정인가요?", why: "같은 '부드러운 고기'라도 조리법에 따라 맞는 부위가 달라요.",
    options: [
      { label: "구이", value: "grill", hint: "안심·채끝·부채살" },
      { label: "불고기·국", value: "bulgogi", hint: "앞다리·양지" },
      { label: "상관없어요", value: "any" },
    ],
  },
  {
    id: "arrival", label: "언제까지 받으셔야 하나요?", why: "냉장 배송은 도착일 보장 여부가 판매처마다 달라요.",
    options: [
      { label: "이번 주 안", value: "this_week" },
      { label: "날짜 지정", value: "date" },
      { label: "상관없어요", value: "any" },
    ],
  },
];

const BEEF: Candidate[] = [
  {
    rank: 1, key: "S101", title: "늘봄한우 1+등급 안심·채끝 구이세트 800g", source: "예시몰", mall: "sample",
    price: 96000, shippingFee: 0, total: 96000, weightLabel: "800g", per100g: 12000,
    delivery: { label: "평일 오후 2시 전 주문 시 다음 날 도착 (판매자 표기)", verified: true },
    reasons: ["안심·채끝은 지방이 적고 결이 고와 씹기 편한 구이 부위예요", "예산 10만원 안에서 1+등급을 확인할 수 있어요"],
    evidence: ["1+등급 표기", "냉장 · 아이스박스 포장", "후기 412개 · 평점 4.8"],
    unverified: ["축산물 등급판정서 사본", "보자기 포장 여부"],
    badges: ["구이용 부드러운 부위"], observed: "2시간 전 조회", isSample: true,
    detail: {
      sellerFacts: [
        { label: "등급", value: "한우 1+등급", source: SAMPLE_SRC },
        { label: "구성", value: "안심 400g + 채끝 400g", source: SAMPLE_SRC },
        { label: "보관", value: "냉장 (수령 후 3일 이내 섭취 권장)", source: SAMPLE_SRC },
        { label: "배송", value: "평일 14시 전 주문 시 다음 날 도착 · 무료배송", source: SAMPLE_SRC },
        { label: "원산지", value: "국내산 (한우)", source: SAMPLE_SRC },
      ],
      reviews: {
        count: 412, rating: 4.8, analyzed: 120, source: { label: "예시몰 상품 리뷰 (예시)", url: null },
        points: [
          { text: "고기가 연하고 부드럽다는 평가가 많아요", tone: "positive", mentions: 64,
            quotes: [{ text: "칠순 아버지가 잘 씹으셨어요. 안심이 특히 연해요." }, { text: "구워 드리니 어머니가 부드럽다고 좋아하셨습니다." }] },
          { text: "선물 포장이 깔끔하다는 후기가 있어요", tone: "positive", mentions: 21,
            quotes: [{ text: "아이스박스에 보냉팩이 넉넉하게 들어 있었어요." }] },
          { text: "채끝은 두께가 고르지 않았다는 의견이 일부 있어요", tone: "negative", mentions: 7,
            quotes: [{ text: "채끝 한 덩이가 얇게 잘려 와서 아쉬웠어요." }] },
        ],
      },
      options: [
        { id: "800", label: "안심·채끝 800g", price: 96000, weightLabel: "800g" },
        { id: "600", label: "안심 600g", price: 89000, weightLabel: "600g" },
      ],
    },
  },
  {
    rank: 2, key: "S102", title: "한우마을 1+등급 불고기·국거리 선물세트 1.2kg", source: "예시몰", mall: "sample",
    price: 89000, shippingFee: 0, total: 89000, weightLabel: "1.2kg", per100g: 7417,
    delivery: { label: "주문 후 1~2일 (도착일 지정 불가)", verified: true },
    reasons: ["얇게 썬 불고기용이라 치아가 약한 분도 드시기 편해요", "1.2kg 로 3~4인 가족이 두 끼 이상 드실 수 있어요"],
    evidence: ["1+등급 표기", "후기 650개 · 평점 4.7", "정가 99,000원 → 할인가"],
    unverified: ["부위별 중량 비율", "도착일 지정"],
    badges: ["양 많음"], observed: "7시간 전 조회", isSample: true,
    detail: {
      sellerFacts: [
        { label: "등급", value: "한우 1+등급", source: SAMPLE_SRC },
        { label: "구성", value: "불고기 600g + 국거리 600g", source: SAMPLE_SRC },
        { label: "보관", value: "냉장 · 아이스박스 포장", source: SAMPLE_SRC },
        { label: "배송", value: "주문 후 1~2일 · 무료배송 · 도착일 지정 불가", source: SAMPLE_SRC },
      ],
      reviews: {
        count: 650, rating: 4.7, analyzed: 150, source: { label: "예시몰 상품 리뷰 (예시)", url: null },
        points: [
          { text: "불고기용이 얇아서 어르신이 드시기 좋다는 후기가 많아요", tone: "positive", mentions: 48,
            quotes: [{ text: "얇게 썰려 와서 양념만 하면 돼서 편했어요." }] },
          { text: "국거리는 기름이 조금 많다는 의견이 있어요", tone: "mixed", mentions: 12,
            quotes: [{ text: "국거리는 지방이 좀 있어서 손질했어요." }] },
        ],
      },
      options: [{ id: "1200", label: "불고기·국거리 1.2kg", price: 89000, weightLabel: "1.2kg" }],
    },
  },
  {
    rank: 3, key: "S103", title: "초원목장 호주산 와규 부채살 구이 1kg", source: "예시몰", mall: "sample",
    price: 69000, shippingFee: 3500, total: 72500, weightLabel: "1kg", per100g: 7250,
    delivery: null,
    reasons: ["부채살은 마블링이 고르게 퍼져 가격 대비 연한 편이에요", "가장 저렴하면서 1kg 이에요"],
    evidence: ["후기 238개 · 평점 4.5", "냉동 · 진공 포장 표기"],
    unverified: ["도착 예정일", "와규 혈통 비율(마블스코어)", "선물 포장"],
    badges: ["가성비"], observed: "1일 전 조회", stale: true, isSample: true,
    detail: {
      sellerFacts: [
        { label: "원산지", value: "호주산", source: SAMPLE_SRC },
        { label: "구성", value: "부채살 250g × 4팩", source: SAMPLE_SRC },
        { label: "보관", value: "냉동 · 진공 포장", source: SAMPLE_SRC },
        { label: "배송비", value: "3,500원", source: SAMPLE_SRC },
      ],
      reviews: {
        count: 238, rating: 4.5, analyzed: 80, source: { label: "예시몰 상품 리뷰 (예시)", url: null },
        points: [
          { text: "가격 대비 부드럽다는 후기가 많아요", tone: "positive", mentions: 30 },
          { text: "힘줄이 씹힌다는 의견이 있어 손질이 필요할 수 있어요", tone: "negative", mentions: 14,
            quotes: [{ text: "가운데 힘줄은 제거하고 구워야 해요." }] },
        ],
      },
      options: [{ id: "1000", label: "부채살 1kg (250g×4)", price: 69000, weightLabel: "1kg" }],
      notes: ["선물용 포장 여부는 판매자 상세페이지에 표기가 없어요."],
    },
  },
];

const BEEF_SPONSORED: Candidate = {
  rank: 0, key: "AD1", title: "산들한우 프리미엄 구이 선물세트 1kg", source: "예시몰", mall: "sample",
  price: 99000, shippingFee: 0, total: 99000, weightLabel: "1kg", per100g: 9900,
  delivery: { label: "주문 후 1~2일 (판매자 표기)", verified: true },
  reasons: ["판매처가 비용을 내고 소개하는 상품이에요"], evidence: [], unverified: ["등급 표기"],
  badges: [], isSample: true, isSponsored: true,
};

/* ───────── 쿠키 시나리오 (1:1 split view 확인용) ───────── */

const COOKIES = [
  { rank: 1, title: "오늘제과 수제 두바이 쫀득쿠키 2개입", price: 9270, shipping_fee: 0, total: 9270, source: "예시몰", mall: "sample", pid: "S000",
    reasoning: "재료 구성이 명확하고 상품평도 비교적 많아서 먼저 살펴볼 만해요.", evidence: ["후기 885개", "무료배송"], unverified: [], is_sample: true,
    unit_price: 4635, unit_count: 2,
    follow_up: [{ label: "이거 더 저렴한 곳 있어?", value: "오늘제과 쫀득쿠키 더 저렴한 곳" }, { label: "단가 비교해줘", value: "오늘제과 쫀득쿠키 단가 비교" }] },
  { rank: 2, title: "달빛베이크 두바이 쫀득 쿠키 1개", price: 7500, shipping_fee: 3500, total: 11000, source: "예시몰", mall: "sample", pid: "S001",
    reasoning: "피스타치오·카다이프가 들어간 수제 스타일이에요.", evidence: ["후기 119개"], unverified: ["도착 예정일"], is_sample: true,
    follow_up: [{ label: "배송비 확인해줘", value: "달빛베이크 쫀득쿠키 배송비 확인" }] },
];

/* ───────── 응답 생성 ───────── */

const NOTICE_SAMPLE: Block = {
  type: "notice",
  data: { md: "지금은 **예시 데이터**로 동작 중이에요. 가격·리뷰 수는 실제 판매 정보가 아니에요.", tone: "warn" },
};

function topicOf(text: string): Topic {
  if (/레시피|만들|요리|재료/.test(text)) return "recipe";
  if (/소고기|한우|고기|와규|불고기/.test(text)) return "beef";
  if (/쿠키|두바이|쫀득/.test(text)) return "cookie";
  return null;
}

const ANSWER_LABEL: Record<string, Record<string, string>> = {
  servings: { "2": "2명", "3-4": "3~4명", "5+": "5명 이상" },
  cooking: { grill: "구이", bulgogi: "불고기·국", any: "" },
  arrival: { this_week: "이번 주 도착", date: "날짜 지정", any: "" },
};

function beefRecommend(answers: Record<string, string>): Block[] {
  const conditions = ["부모님 선물", "부드러운 소고기", "10만원 이하",
    ...Object.entries(answers).map(([k, v]) => ANSWER_LABEL[k]?.[v]).filter((x): x is string => !!x)];
  let cands = [...BEEF];
  if (answers.cooking === "bulgogi") cands = [BEEF[1], BEEF[0], BEEF[2]];
  cands = cands.map((c, i) => ({ ...c, rank: i + 1 }));
  return [
    { type: "text", data: { md: "조건에 맞는 후보 **3개**를 같은 기준으로 비교했어요. 총가격은 배송비를 포함한 금액이에요." } },
    { type: "candidate_compare", data: { title: "후보 비교", conditions, candidates: cands } },
    NOTICE_SAMPLE,
    { type: "sponsored_list", data: { note: "아래는 판매처가 비용을 내고 소개하는 상품이에요. 위 추천 순위와 별개로 표시하며 순위에 반영하지 않아요.", items: [BEEF_SPONSORED] } },
    { type: "chips", data: { mode: "message", items: ["더 저렴한 것", "양 많은 순", "도착일 보장되는 것만"] } },
  ];
}

export async function mockChat(req: ChatRequest): Promise<ChatResponse> {
  await new Promise((r) => setTimeout(r, 450));
  const sid = req.session_id ?? `mock-${Math.random().toString(36).slice(2, 8)}`;
  const s = sessions.get(sid) ?? { topic: null, answered: false, answers: {} };
  sessions.set(sid, s);
  const text = (req.message ?? req.chip ?? "").trim();
  const reply = (blocks: Block[], stage: string): ChatResponse => ({ session_id: sid, stage, blocks });

  if (req.answers) {
    s.answers = { ...s.answers, ...req.answers };
    s.answered = true;
    if (s.topic === "beef") return reply(beefRecommend(s.answers), "recommend");
  }

  const t = text ? topicOf(text) : null;
  if (t && t !== s.topic) { s.topic = t; s.answered = false; s.answers = {}; }

  if (s.topic === "recipe" && text) {
    return reply([
      { type: "text", data: { md: "레시피 연계는 **메뉴 선택 → 보유 재료 확인 → 부족한 재료만 추천** 순서로 진행돼요. 이번 버전에서는 화면 흐름만 미리 보여 드려요." } },
      { type: "clarify_form", data: { layout: "sequential", submit: "부족한 재료 확인하기", questions: [
        { id: "menu", label: "어떤 요리를 하실 건가요?", why: "메뉴에 따라 필요한 재료와 양이 정해져요.", options: [
          { label: "소고기 미역국", value: "miyeokguk" }, { label: "불고기", value: "bulgogi" }, { label: "토마토 파스타", value: "pasta" }] },
        { id: "owned", label: "집에 있는 재료를 골라 주세요", why: "가지고 계신 재료는 추천에서 빼요.", options: [
          { label: "간장·참기름 있음", value: "sauce" }, { label: "채소 있음", value: "veg" }, { label: "아무것도 없음", value: "none" }] },
      ] } },
      { type: "notice", data: { md: "레시피 재료 추천은 다음 단계에서 `/api/recipe/plan` 과 연결됩니다.", tone: "info" } },
    ], "clarify");
  }

  if (s.topic === "beef") {
    if (!s.answered && text && !/저렴|많은|보장/.test(text)) {
      return reply([
        { type: "text", data: { md: "**부모님 선물 · 부드러운 소고기 · 10만원 이하**로 이해했어요. 고르는 데 영향을 주는 것만 3가지 여쭤볼게요." } },
        { type: "clarify_form", data: { layout: "sequential", submit: "이 조건으로 후보 보기", questions: BEEF_QUESTIONS } },
      ], "clarify");
    }
    if (/저렴/.test(text)) {
      return reply([
        { type: "text", data: { md: "총가격이 낮은 순으로 다시 정리했어요." } },
        { type: "candidate_compare", data: { candidates: [...BEEF].sort((a, b) => (a.total ?? 0) - (b.total ?? 0)).map((c, i) => ({ ...c, rank: i + 1 })) } },
        NOTICE_SAMPLE,
      ], "refine");
    }
    if (/많은/.test(text)) {
      return reply([
        { type: "text", data: { md: "중량이 많은 순이에요. 100g당 가격도 함께 보세요." } },
        { type: "candidate_compare", data: { candidates: [BEEF[1], BEEF[2], BEEF[0]].map((c, i) => ({ ...c, rank: i + 1 })) } },
      ], "refine");
    }
    if (/보장/.test(text)) {
      return reply([
        { type: "text", data: { md: "도착일이 판매자 상세페이지에 **표기된** 상품만 남겼어요. '초원목장 부채살'은 도착 예정일 표기가 없어 제외했어요." } },
        { type: "comparison_pair", data: { pairs: [{ pair_index: 0, compare: true, cards: [BEEF[0], BEEF[1]].map((c, i) => ({
          rank: i + 1, title: c.title, price: c.price, shipping_fee: c.shippingFee, total: c.total, source: c.source, mall: c.mall, pid: c.key,
          reasoning: c.reasons[0], delivery_terms: c.delivery?.label, evidence: c.evidence, unverified: c.unverified, is_sample: true,
        })), chips: [{ label: "둘 중 뭐가 나아?", value: "늘봄한우 vs 한우마을 비교" }] }] } },
      ], "refine");
    }
    return reply([
      { type: "text", data: { md: "두 후보 모두 1+등급이에요. **구이로 드실 거면 늘봄한우**, **양과 활용도를 보면 한우마을**이 맞아요." } },
      { type: "chips", data: { mode: "message", items: ["더 저렴한 것", "도착일 보장되는 것만"] } },
    ], "explore");
  }

  if (s.topic === "cookie") {
    return reply([
      { type: "text", data: { md: "두바이 쫀득쿠키 추천 결과예요. 두 상품을 나란히 비교해 보세요." } },
      { type: "comparison_pair", data: { pairs: [{ pair_index: 0, compare: true, cards: COOKIES, chips: [{ label: "둘 중 뭐가 나아?", value: "오늘제과 vs 달빛베이크 비교" }] }] } },
      NOTICE_SAMPLE,
      { type: "clarify_form", data: { title: "예산은 얼마인가요?", options: [{ label: "1만원 이하", value: "0-10000" }, { label: "1~2만원", value: "10000-20000" }] } },
      { type: "chips", data: { mode: "chip", items: ["더 저렴한 것", "프리미엄으로"] } },
    ], "recommend");
  }

  return reply([
    { type: "text", data: { md: "어떤 상품을 찾고 계세요? 받는 분·예산·용도를 함께 말씀해 주시면 더 정확해요." } },
    { type: "chips", data: { mode: "message", items: ["부모님 드릴 부드러운 소고기, 10만원 안쪽", "두바이 쫀득쿠키", "소고기 미역국 재료"] } },
  ], "understand");
}
