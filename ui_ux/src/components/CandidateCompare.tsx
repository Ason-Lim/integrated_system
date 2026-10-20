import type { ReactNode } from "react";
import type { Candidate, CandidateCompareBlock } from "../types/blocks";
import { useChatActions } from "./ChatActions";
import { EvidenceTags, SourceMeta, Thumb, TotalPrice, UnverifiedTags } from "./ui";
import { cx, won } from "../lib/format";

/**
 * ③ 후보 비교 — 3개 내외 후보를 같은 기준(총가격·중량·배송·선택 이유·확인되지 않은 조건)으로 비교.
 * PC(md 이상): 열 = 상품, 행 = 기준인 비교표.  모바일: 같은 행 순서의 카드 세로 쌓기.
 */
export function CandidateCompare({ block }: { block: CandidateCompareBlock }) {
  const { candidates, conditions, title } = block.data;
  const { openDetail } = useChatActions();
  if (!candidates.length) return null;

  const totals = candidates.map((c) => c.total).filter((v): v is number => v != null);
  const minTotal = totals.length ? Math.min(...totals) : null;
  const per = candidates.map((c) => c.per100g).filter((v): v is number => v != null);
  const minPer = per.length > 1 ? Math.min(...per) : null;

  const isBestTotal = (c: Candidate) => minTotal != null && c.total === minTotal && totals.length > 1;

  return (
    <section aria-label={title ?? "후보 비교"} className="my-3">
      {conditions?.length ? (
        <div className="mb-3 flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-ink3">적용한 조건</span>
          {conditions.map((c) => <span key={c} className="rounded-full border border-line bg-surface px-2.5 py-0.5">{c}</span>)}
        </div>
      ) : null}

      {/* ── PC: 비교표 ── */}
      <div className="card hidden overflow-x-auto md:block">
        <table className="w-full table-fixed border-collapse text-sm">
          <colgroup>
            <col className="w-[112px]" />
            {candidates.map((c) => <col key={c.key} />)}
          </colgroup>
          <thead>
            <tr className="align-top">
              <th className="p-4" />
              {candidates.map((c) => (
                <th key={c.key} className="p-4 text-left font-normal">
                  <div className="flex items-start gap-3">
                    <Thumb c={c} size="sm" />
                    <div className="min-w-0">
                      <span className="text-xs font-bold text-accent">후보 {c.rank}</span>
                      <button type="button" onClick={() => openDetail(c)}
                        className="block text-left text-[15px] font-bold leading-snug hover:underline">{c.title}</button>
                    </div>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <Row label="총가격">{candidates.map((c) => <TotalPrice key={c.key} c={c} best={isBestTotal(c)} />)}</Row>
            <Row label="중량">
              {candidates.map((c) => (
                <div key={c.key}>
                  <div className="font-semibold">{c.weightLabel ?? <span className="text-warn">표기 없음</span>}</div>
                  {c.per100g != null && <div className={cx("text-xs", c.per100g === minPer ? "font-semibold text-accent" : "text-ink2")}>100g당 {won(c.per100g)}</div>}
                  {c.unitLabel && <div className="text-xs text-ink2">{c.unitLabel}</div>}
                </div>
              ))}
            </Row>
            <Row label="배송">{candidates.map((c) => <Delivery key={c.key} c={c} />)}</Row>
            <Row label="선택 이유">
              {candidates.map((c) => (
                <ul key={c.key} className="space-y-1 text-ink2">
                  {c.reasons.map((r) => <li key={r} className="leading-snug">· {r}</li>)}
                </ul>
              ))}
            </Row>
            <Row label="확인되지 않은 조건">{candidates.map((c) => <UnverifiedTags key={c.key} items={c.unverified} compact />)}</Row>
            <Row label="출처">{candidates.map((c) => <SourceMeta key={c.key} c={c} />)}</Row>
            <tr>
              <td />
              {candidates.map((c) => (
                <td key={c.key} className="px-4 pb-4">
                  <button type="button" className="ghost-btn w-full" onClick={() => openDetail(c)}>상세·리뷰 근거 보기</button>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      {/* ── 모바일: 카드 ── */}
      <div className="space-y-3 md:hidden">
        {candidates.map((c) => (
          <article key={c.key} className="card rise p-4">
            <div className="flex gap-3">
              <Thumb c={c} />
              <div className="min-w-0 flex-1">
                <span className="text-xs font-bold text-accent">후보 {c.rank}</span>
                <h3 className="text-base font-bold leading-snug">{c.title}</h3>
                <div className="mt-1"><TotalPrice c={c} best={isBestTotal(c)} /></div>
              </div>
            </div>
            <dl className="mt-3 grid grid-cols-[76px_1fr] gap-x-3 gap-y-2 border-t border-line pt-3 text-sm">
              <dt className="text-ink3">중량</dt>
              <dd>
                {c.weightLabel ?? <span className="text-warn">표기 없음</span>}
                {c.per100g != null && <span className={cx("ml-1.5 text-xs", c.per100g === minPer ? "font-semibold text-accent" : "text-ink2")}>100g당 {won(c.per100g)}</span>}
              </dd>
              <dt className="text-ink3">배송</dt>
              <dd><Delivery c={c} /></dd>
              <dt className="text-ink3">선택 이유</dt>
              <dd className="space-y-0.5 text-ink2">{c.reasons.map((r) => <p key={r}>· {r}</p>)}</dd>
              <dt className="text-ink3">미확인</dt>
              <dd><UnverifiedTags items={c.unverified} compact /></dd>
            </dl>
            <div className="mt-3 flex items-center justify-between gap-2">
              <SourceMeta c={c} />
              <button type="button" className="ghost-btn shrink-0" onClick={() => openDetail(c)}>상세 보기</button>
            </div>
          </article>
        ))}
      </div>

      {candidates.some((c) => c.evidence.length) && (
        <details className="mt-2 text-sm text-ink2">
          <summary className="cursor-pointer select-none py-1 text-ink3">확인된 근거 펼치기</summary>
          <div className="mt-2 space-y-2">
            {candidates.map((c) => (
              <div key={c.key} className="flex flex-wrap items-center gap-2">
                <span className="w-14 shrink-0 text-xs font-bold text-accent">후보 {c.rank}</span>
                <EvidenceTags items={c.evidence} />
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode[] }) {
  return (
    <tr className="border-t border-line align-top">
      <th scope="row" className="p-4 text-left text-xs font-semibold text-ink3">{label}</th>
      {children.map((ch, i) => <td key={i} className="p-4">{ch}</td>)}
    </tr>
  );
}

function Delivery({ c }: { c: Candidate }) {
  if (!c.delivery) return <span className="font-semibold text-warn">도착 예정일 표기 없음</span>;
  return <span className="leading-snug">{c.delivery.label}</span>;
}
