export const won = (v: number | null | undefined): string =>
  v == null ? "미확인" : `${v.toLocaleString("ko-KR")}원`;

export const weightLabel = (g: number | null | undefined): string | null => {
  if (!g) return null;
  return g >= 1000 ? `${+(g / 1000).toFixed(2)}kg` : `${g}g`;
};

export const per100g = (total: number | null, g: number | null | undefined): number | null =>
  total != null && g ? Math.round((total / g) * 100) : null;

/** 상품명에서 중량 추정 ("1.2kg", "800g") — 백엔드가 weight_g 를 내려주기 전까지의 보조 수단 */
export const parseWeightFromTitle = (title: string): number | null => {
  const kg = title.match(/(\d+(?:\.\d+)?)\s*kg/i);
  if (kg) return Math.round(parseFloat(kg[1]) * 1000);
  const g = title.match(/(\d+(?:\.\d+)?)\s*g(?![a-z])/i);
  return g ? Math.round(parseFloat(g[1])) : null;
};

export const cx = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(" ");
