/**
 * 서버 주도 UI(server-driven UI) 블록 계약.
 *
 * - 기존 블록: consumer/presenter.py 가 이미 내려주는 형태 (text · notice · verdict · product_list ·
 *   comparison_pair · clarify_form · chips · shipping_options)
 * - 제안 블록: 이번 화면 흐름을 위해 추가를 제안하는 형태 (candidate_compare · sponsored_list)
 *   → 백엔드가 아직 내려주지 않으면 api/adapt.ts 가 기존 블록에서 만들어 준다.
 */

export type ChipMode = "chip" | "message";

export interface ChipItem {
  label: string;
  /** 서버로 보낼 값. 없으면 label 을 그대로 보낸다. */
  value?: string;
}

/* ───────── 기존 블록 ───────── */

export interface TextBlock { type: "text"; data: { md?: string; text?: string } }
export interface NoticeBlock { type: "notice"; data: { md: string; tone?: "info" | "warn"; affiliate?: boolean } }
export interface VerdictBlock { type: "verdict"; data: { md: string } }

export interface ChipsBlock {
  type: "chips";
  data: { items: (string | ChipItem)[]; mode?: ChipMode };
}

export interface ClarifyOption { label: string; value: string; hint?: string }
export interface ClarifyQuestion {
  id: string;
  label: string;
  /** 왜 묻는지 — 선택에 어떤 영향을 주는지 한 줄 (제안 필드) */
  why?: string;
  options: ClarifyOption[];
  /** 건너뛰기 허용 여부 (제안 필드, 기본 true) */
  skippable?: boolean;
}
export interface ClarifyFormBlock {
  type: "clarify_form";
  data: {
    questions?: ClarifyQuestion[];
    submit?: string;
    /** 첨부 예시 형식 호환: 질문 1개짜리 */
    title?: string;
    options?: ClarifyOption[];
    /** 제안 필드: 'sequential' 이면 한 번에 한 질문씩 보여 준다 */
    layout?: "sequential" | "stacked";
  };
}

/** presenter.card() 가 만드는 카드 (필드 일부) */
export interface ApiCard {
  rank: number;
  mall?: string;
  pid?: string | null;
  title: string;
  image?: string | null;
  image_url?: string | null;
  price: number;
  shipping_fee?: number | null;
  total?: number | null;
  original_price?: number | null;
  unit_price?: number | null;
  unit_count?: number | null;
  spec?: string | null;
  reason?: string;
  reasoning?: string;
  evidence?: string[];
  unverified?: string[];
  badges?: string[];
  source?: string;
  observed?: string;
  stale?: boolean;
  url?: string | null;
  is_sample?: boolean;
  cta?: string;
  follow_up?: ChipItem[];
  rankable?: boolean;
  missing_terms?: string[];
  /* 제안 필드 (백엔드 추가 요청) */
  weight_g?: number | null;
  delivery_terms?: string | null;
  is_sponsored?: boolean;
  /** 수수료가 발생하는 제휴 링크 (쿠팡 파트너스 등) */
  affiliate?: boolean;
  affiliate_program?: string | null;
  /** 평점·후기·도착일을 판매처 API가 제공하지 않음 → 판매처에서 확인 안내 */
  check_at_mall?: boolean;
  delivery_hint?: string | null;
  detail?: ProductDetail;
}

export interface ComparisonPair {
  pair_index: number;
  cards: ApiCard[];
  compare?: boolean;
  chips?: ChipItem[];
}
export interface ComparisonPairBlock { type: "comparison_pair"; data: { pairs: ComparisonPair[] } }
export interface ProductListBlock { type: "product_list"; data: { items: ApiCard[]; compare?: boolean } }

export interface ShippingEstimate {
  agency?: string;
  total_krw?: number;
  eta_days_min?: number;
  eta_days_max?: number;
  shipping_krw?: number;
  duty_krw?: number;
  vat_krw?: number;
}
export interface ShippingOptionsBlock {
  type: "shipping_options";
  data: {
    title?: string;
    note?: string;
    options?: { id: string; label: string; desc?: string }[];
    items?: { title: string; mall?: string; estimate?: ShippingEstimate }[];
    /* 첨부 예시 형식 호환 */
    is_overseas?: boolean;
    estimated_days?: string;
    total_landed_cost?: number;
    agency?: string;
  };
}

/* ───────── 제안 블록 ───────── */

/** ③ 후보 비교 — 3개 내외 후보를 같은 기준으로 나란히 비교 */
export interface CandidateCompareBlock {
  type: "candidate_compare";
  data: {
    title?: string;
    /** 사용자가 고른 조건 요약 (예: "3~4인 · 구이용 · 이번 주 도착") */
    conditions?: string[];
    candidates: Candidate[];
  };
}

/** 유료 소개 — 일반 추천 순위와 분리해 별도 영역에 표시 */
export interface SponsoredListBlock {
  type: "sponsored_list";
  data: { note?: string; items: Candidate[] };
}

export type Block =
  | TextBlock | NoticeBlock | VerdictBlock | ChipsBlock | ClarifyFormBlock
  | ComparisonPairBlock | ProductListBlock | ShippingOptionsBlock
  | CandidateCompareBlock | SponsoredListBlock;

export interface ChatResponse {
  session_id: string;
  stage?: string;
  slots?: Record<string, unknown>;
  blocks: Block[];
}

export interface ChatRequest {
  session_id: string | null;
  message?: string;
  answers?: Record<string, string>;
  chip?: string;
}

/* ───────── 화면용 뷰 모델 ───────── */

export interface Candidate {
  rank: number;
  key: string;
  title: string;
  image?: string | null;
  source: string;          // 판매처 표시명
  mall?: string;
  price: number;
  shippingFee: number | null;   // null = 미확인 (0원과 다름)
  total: number | null;         // null = 배송비 미확인으로 확정 불가
  weightLabel?: string | null;  // "1.2kg"
  per100g?: number | null;      // 100g당 가격
  unitLabel?: string | null;    // "개당 약 4,635원"
  delivery?: { label: string; verified: boolean } | null;
  reasons: string[];            // 선택 이유
  evidence: string[];           // 확인된 근거
  unverified: string[];         // 확인되지 않은 조건
  badges: string[];
  observed?: string;
  stale?: boolean;
  url?: string | null;
  isSample?: boolean;
  isSponsored?: boolean;
  affiliate?: boolean;
  affiliateProgram?: string | null;
  checkAtMall?: boolean;
  deliveryHint?: string | null;
  followUp?: ChipItem[];
  detail?: ProductDetail;
}

/** ④ 상품 판단 — 판매자 표기와 리뷰 근거를 분리 */
export interface SourceRef { label: string; url?: string | null }

export interface SellerFact {
  label: string;        // "등급", "원산지", "중량", "배송"
  value: string;
  source?: SourceRef;   // 판매자 상세페이지 원문
}

export interface ReviewPoint {
  text: string;                   // "고기가 부드럽다는 후기가 많아요"
  tone: "positive" | "negative" | "mixed";
  mentions?: number;              // 언급 리뷰 수
  quotes?: { text: string; source?: SourceRef }[];
}

export interface ProductDetail {
  sellerFacts: SellerFact[];
  reviews?: {
    count?: number;
    rating?: number;
    analyzed?: number;            // 요약에 사용한 리뷰 수
    points: ReviewPoint[];
    source?: SourceRef;
  } | null;
  options?: { id: string; label: string; price: number; weightLabel?: string }[];
  notes?: string[];
}
