import type { ShippingOptionsBlock } from "../types/blocks";
import { won } from "../lib/format";

/** 해외 접속 시에만 서버가 내려주는 블록. 예상 배송 기간과 최종 견적을 강조한다. */
export function ShippingOptions({ block }: { block: ShippingOptionsBlock }) {
  const d = block.data;
  // 첨부 예시 형식(단일 견적)과 presenter 형식(상품별 견적)을 모두 받는다
  const rows = d.items?.length
    ? d.items.map((it) => ({
        title: it.title,
        days: it.estimate?.eta_days_min != null ? `${it.estimate.eta_days_min}–${it.estimate.eta_days_max}일` : null,
        total: it.estimate?.total_krw ?? null,
        agency: it.estimate?.agency ?? null,
      }))
    : [{ title: null as string | null, days: d.estimated_days ?? null, total: d.total_landed_cost ?? null, agency: d.agency ?? null }];

  return (
    <section className="card my-3 overflow-hidden" aria-label="해외 배송 옵션">
      <div className="border-b border-line bg-reviewSoft px-4 py-3">
        <h3 className="font-bold text-review">✈ {d.title ?? "해외 배송 옵션"}</h3>
        {d.note && <p className="mt-0.5 text-sm text-ink2">{d.note}</p>}
      </div>
      <div className="divide-y divide-line">
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-2 gap-3 px-4 py-3 sm:grid-cols-[1fr_auto_auto] sm:items-center">
            {r.title && <div className="col-span-2 text-sm font-semibold sm:col-span-1">{r.title}</div>}
            <div>
              <div className="text-xs text-ink3">예상 배송 기간</div>
              <div className="text-lg font-extrabold">{r.days ?? <span className="text-base text-warn">견적 불가</span>}</div>
            </div>
            <div className="text-right sm:min-w-[140px]">
              <div className="text-xs text-ink3">최종 견적 {r.agency ? `· ${r.agency}` : ""}</div>
              <div className="text-lg font-extrabold text-accent">{r.total != null ? won(r.total) : <span className="text-base text-warn">미확인</span>}</div>
            </div>
          </div>
        ))}
      </div>
      {!!d.options?.length && (
        <ul className="grid gap-2 border-t border-line p-4 sm:grid-cols-3">
          {d.options.map((o) => (
            <li key={o.id} className="rounded-xl bg-chip px-3 py-2 text-sm">
              <b className="block">{o.label}</b><span className="text-ink2">{o.desc}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
