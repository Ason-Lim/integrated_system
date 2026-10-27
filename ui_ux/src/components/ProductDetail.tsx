import { useEffect, useRef, useState } from "react";
import type { Candidate, ReviewPoint, SourceRef } from "../types/blocks";
import { goUrl } from "../api/client";
import { cx, won } from "../lib/format";
import { EvidenceTags, SourceMeta, Thumb, TotalPrice, UnverifiedTags } from "./ui";

interface Props {
  c: Candidate;
  sessionId: string | null;
  purchasing: boolean;
  onPurchasing: (v: boolean) => void;
  onClose: () => void;
}

/**
 * ④ 상품 판단 — '판매자 표기'와 '리뷰 근거'를 시각적으로 분리하고 각각 원문으로 연결.
 * ⑤ 구매 연결(미리보기) — 옵션·수량·배송비를 확인한 뒤 판매처로 이동.
 * PC: 오른쪽 패널 / 모바일: 아래에서 올라오는 시트.
 */
export function ProductDetail({ c, sessionId, purchasing, onPurchasing, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [onClose]);

  const d = c.detail;
  return (
    <div className="fixed inset-0 z-40">
      <button type="button" aria-label="닫기" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={`${c.title} 상세`}
        className="sheet-anim absolute inset-x-0 bottom-0 flex max-h-[90dvh] flex-col rounded-t-[24px] bg-surface outline-none
                   lg:inset-y-0 lg:left-auto lg:right-0 lg:max-h-none lg:w-[480px] lg:rounded-none lg:border-l lg:border-line">
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-line lg:hidden" aria-hidden />

        {/* 머리 */}
        <header className="flex items-start gap-3 border-b border-line px-5 pb-4 pt-3 lg:pt-5">
          <Thumb c={c} />
          <div className="min-w-0 flex-1">
            {c.isSponsored
              ? <span className="tag bg-sponsorSoft text-sponsor">유료 소개</span>
              : <span className="text-xs font-bold text-accent">후보 {c.rank}</span>}
            <h2 className="text-lg font-bold leading-snug">{c.title}</h2>
            <div className="mt-1"><TotalPrice c={c} /></div>
          </div>
          <button type="button" onClick={onClose} aria-label="닫기"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-line text-ink2 hover:border-ink3">✕</button>
        </header>

        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
          {purchasing ? <PurchaseConfirm c={c} /> : (
            <>
              {/* 판매자 표기 */}
              <section aria-labelledby="sf">
                <SectionHead id="sf" tone="seller" title="판매자 표기" desc="판매자가 상세페이지에 직접 적은 내용이에요. 사실 여부는 판매자 책임이에요." />
                <dl className="divide-y divide-line rounded-2xl border border-line">
                  {(d?.sellerFacts ?? []).map((f) => (
                    <div key={f.label} className="grid grid-cols-[72px_1fr_auto] items-start gap-3 px-4 py-2.5 text-sm">
                      <dt className="text-ink3">{f.label}</dt>
                      <dd className="font-medium">{f.value}</dd>
                      <SourceLink s={f.source} />
                    </div>
                  ))}
                </dl>
              </section>

              {/* 리뷰 근거 */}
              <section aria-labelledby="rv">
                <SectionHead id="rv" tone="review" title="리뷰 근거"
                  desc={d?.reviews
                    ? `구매자 리뷰 ${d.reviews.analyzed ?? "일부"}개를 읽고 자주 나온 내용을 묶었어요. 원문을 펼쳐 확인할 수 있어요.`
                    : "구매자 리뷰를 요약한 내용이 여기에 표시돼요."} />
                {d?.reviews ? (
                  <>
                    <div className="mb-3 flex items-center gap-3 text-sm">
                      {d.reviews.rating != null && <span className="text-lg font-extrabold">★ {d.reviews.rating}</span>}
                      {d.reviews.count != null && <span className="text-ink2">리뷰 {d.reviews.count.toLocaleString()}개</span>}
                      <span className="ml-auto"><SourceLink s={d.reviews.source} label="리뷰 원문" /></span>
                    </div>
                    <ul className="space-y-2">{d.reviews.points.map((p) => <ReviewItem key={p.text} p={p} />)}</ul>
                  </>
                ) : (
                  <p className="rounded-2xl bg-chip px-4 py-3 text-sm text-ink2">이 상품은 아직 리뷰 요약이 없어요. 판매처 페이지에서 리뷰를 직접 확인해 주세요.</p>
                )}
              </section>

              {/* 확인되지 않은 조건 */}
              <section aria-labelledby="uv">
                <SectionHead id="uv" tone="warn" title="확인되지 않은 조건" desc="판매자 표기와 리뷰 어디에서도 확인하지 못했어요. 구매 전에 판매처에 문의해 보세요." />
                <UnverifiedTags items={c.unverified} />
              </section>

              {!!c.evidence.length && (
                <section>
                  <h3 className="mb-2 text-sm font-bold">추천에 쓴 근거</h3>
                  <EvidenceTags items={c.evidence} />
                </section>
              )}
              {d?.notes?.map((n) => <p key={n} className="text-xs text-ink3">※ {n}</p>)}
              <SourceMeta c={c} />
            </>
          )}
        </div>

        {/* 하단 행동 */}
        <footer className="border-t border-line px-5 pb-[calc(16px+env(safe-area-inset-bottom))] pt-3">
          {purchasing ? (
            <div className="flex gap-2">
              <button type="button" className="ghost-btn" onClick={() => onPurchasing(false)}>← 상세</button>
              <GoButton c={c} sessionId={sessionId} />
            </div>
          ) : (
            <button type="button" className="primary-btn w-full" onClick={() => onPurchasing(true)}>
              이 상품으로 옵션·배송비 확인
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}

function SectionHead({ id, title, desc, tone }: { id: string; title: string; desc: string; tone: "seller" | "review" | "warn" }) {
  const dot = tone === "seller" ? "bg-ink" : tone === "review" ? "bg-review" : "bg-warn";
  return (
    <div className="mb-2.5">
      <h3 id={id} className="flex items-center gap-2 font-bold"><i className={cx("h-2 w-2 rounded-full", dot)} />{title}</h3>
      <p className="mt-0.5 text-xs leading-relaxed text-ink3">{desc}</p>
    </div>
  );
}

function SourceLink({ s, label = "원문" }: { s?: SourceRef; label?: string }) {
  if (!s) return <span className="text-xs text-ink3">출처 없음</span>;
  if (!s.url) return <span className="text-xs text-ink3" title={s.label}>{label} 링크 없음</span>;
  return (
    <a href={s.url} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap text-xs font-semibold text-review underline underline-offset-2">
      {label} ↗
    </a>
  );
}

function ReviewItem({ p }: { p: ReviewPoint }) {
  const [open, setOpen] = useState(false);
  const icon = p.tone === "positive" ? "＋" : p.tone === "negative" ? "－" : "±";
  const color = p.tone === "positive" ? "text-accent bg-accentSoft" : p.tone === "negative" ? "text-warn bg-warnSoft" : "text-ink2 bg-chip";
  return (
    <li className="rounded-2xl border border-line bg-reviewSoft/30 px-4 py-3">
      <div className="flex items-start gap-2.5">
        <span className={cx("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-xs font-bold", color)}>{icon}</span>
        <div className="flex-1 text-sm">
          <p className="font-medium leading-snug">{p.text}</p>
          {p.mentions != null && <p className="text-xs text-ink3">리뷰 {p.mentions}개에서 언급</p>}
        </div>
        {!!p.quotes?.length && (
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
            className="shrink-0 text-xs font-semibold text-review">{open ? "접기" : "원문 보기"}</button>
        )}
      </div>
      {open && (
        <ul className="mt-2 space-y-1.5 border-l-2 border-review/40 pl-3 text-sm text-ink2">
          {p.quotes!.map((q) => (
            <li key={q.text}>“{q.text}” {q.source?.url && <SourceLink s={q.source} />}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** ⑤ 구매 연결 미리보기 — 정확한 옵션·수량·배송비를 확인 */
function PurchaseConfirm({ c }: { c: Candidate }) {
  const opts = c.detail?.options?.length ? c.detail.options : [{ id: "base", label: c.weightLabel ?? "기본 구성", price: c.price }];
  const [opt, setOpt] = useState(opts[0].id);
  const [qty, setQty] = useState(1);
  const o = opts.find((x) => x.id === opt) ?? opts[0];
  const ship = c.shippingFee;
  const total = ship == null ? null : o.price * qty + ship;
  return (
    <section className="space-y-5">
      <div>
        <h3 className="font-bold">옵션 선택</h3>
        <div role="radiogroup" className="mt-2 space-y-2">
          {opts.map((x) => (
            <button key={x.id} type="button" role="radio" aria-checked={opt === x.id} onClick={() => setOpt(x.id)}
              className={cx("flex w-full items-center justify-between rounded-2xl border-[1.5px] px-4 py-3 text-left",
                opt === x.id ? "border-ink" : "border-line")}>
              <span className="font-medium">{x.label}</span><span className="font-bold">{won(x.price)}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-between">
        <h3 className="font-bold">수량</h3>
        <div className="flex items-center gap-1 rounded-full border border-line p-1">
          <button type="button" aria-label="수량 줄이기" className="h-8 w-8 rounded-full hover:bg-chip" onClick={() => setQty((q) => Math.max(1, q - 1))}>−</button>
          <span className="w-8 text-center font-bold tabular-nums">{qty}</span>
          <button type="button" aria-label="수량 늘리기" className="h-8 w-8 rounded-full hover:bg-chip" onClick={() => setQty((q) => Math.min(9, q + 1))}>＋</button>
        </div>
      </div>
      <dl className="space-y-1.5 rounded-2xl bg-chip px-4 py-3 text-sm">
        <div className="flex justify-between"><dt className="text-ink2">상품가</dt><dd>{won(o.price)} × {qty}</dd></div>
        <div className="flex justify-between"><dt className="text-ink2">배송비</dt>
          <dd className={cx(ship == null && "font-semibold text-warn")}>{ship == null ? "판매처에서 확인 필요" : ship === 0 ? "무료" : won(ship)}</dd></div>
        <div className="flex justify-between border-t border-line pt-1.5 text-base font-extrabold">
          <dt>결제 예상 금액</dt><dd>{total == null ? "확정 불가" : won(total)}</dd></div>
      </dl>
      <p className="text-xs leading-relaxed text-ink3">
        결제는 판매처에서 진행돼요. {c.observed ? `가격은 ${c.observed} 기준이며, ` : ""}이동 후 실제 가격·배송비가 다를 수 있으니 결제 화면에서 한 번 더 확인해 주세요.
      </p>
    </section>
  );
}

function GoButton({ c, sessionId }: { c: Candidate; sessionId: string | null }) {
  // 유료 소개는 추천 순위(last_items)에 없으므로 /go 대신 판매처 URL 로 직접 이동 (rel=sponsored)
  if (c.isSponsored && c.url) {
    return <a href={c.url} target="_blank" rel="sponsored noopener noreferrer" className="primary-btn flex-1">{c.source}에서 결제하기 ↗</a>;
  }
  const href = c.url ? goUrl(sessionId, c.rank) : null;
  if (!href) {
    return (
      <button type="button" disabled className="primary-btn flex-1">
        {c.isSample ? "예시 데이터 · 링크 없음" : "판매처 링크 없음"}
      </button>
    );
  }
  // 제휴(수수료) 링크는 rel="sponsored" 로 표시하고 버튼 바로 아래에 고지한다
  return (
    <div className="flex flex-1 flex-col gap-1">
      <a href={href} target="_blank" rel={c.affiliate ? "sponsored noopener" : "noopener"} className="primary-btn">{c.source}에서 결제하기 ↗</a>
      {c.affiliate && (
        <p className="text-center text-[11px] leading-snug text-ink3">
          {c.affiliateProgram ?? "제휴"} 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다. 수수료는 본 사이트 운영에 도움이 됩니다.
        </p>
      )}
    </div>
  );
}
