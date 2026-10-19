"""분석 리포트(HTML) — 첨부된 2026-10-12 검토본(ibk_food_candidates / supplier_evidence_pilot)의 구성을 따르되
한 장에서 '판정 → 근거 → 다음 행동'이 보이도록 재구성.

구성: ① 판정 요약 스트립 ② 추출 조건(원문 발췌) ③ 카테고리 충족도 ④ 후보 × 확인항목 매트릭스
      ⑤ 1인 비용 구조 ⑥ 견적 요청 초안 ⑦ 판단 규칙·한계
"""
from __future__ import annotations

import html
from datetime import date

from b2b.costing import CostAnalysis
from b2b.models import BidRequirement, Evaluation

E = html.escape
LABELS = {"bid_id": "공고번호", "agency": "발주기관", "title": "사업명", "headcount": "예정 인원",
          "budget_per_person": "1인당 예산", "vat_included": "VAT", "total_budget": "총예산", "categories": "품목 구성",
          "min_online_price": "온라인가 하한", "setup_days": "폐쇄몰 구축", "delivery_business_days": "배송 기한",
          "exchange_business_days": "교환 기한", "deadline": "마감일", "settlement": "정산"}
ICON = {"PASS": ("●", "pass", "충족"), "FAIL": ("✕", "fail", "위반"), "UNKNOWN": ("?", "unk", "미확인")}
DEC = {"ELIGIBLE": ("적격", "ok"), "HOLD": ("보류", "hold"), "EXCLUDED": ("제외", "ex")}


def _val(field: str, v) -> str:
    if field in ("budget_per_person", "total_budget", "min_online_price") and isinstance(v, (int, float)):
        return f"{int(v):,}원"
    if field == "headcount":
        return f"{int(v):,}명"
    if field == "vat_included":
        return "포함" if v in (True, "True") else "별도"
    if field in ("setup_days",):
        return f"{v}일 이내"
    if field in ("delivery_business_days", "exchange_business_days"):
        return f"{v}영업일 이내"
    return str(v)


def render(req: BidRequirement, evals: list[Evaluation], cov: list[dict], cost: CostAnalysis | None,
           rfqs: list[dict], today: date | None = None) -> str:
    today = today or date.today()
    n = {k: sum(e.decision == k for e in evals) for k in DEC}
    keys: list[tuple[str, str]] = []
    for e in evals:
        for c in e.checks:
            if (c.key, c.label) not in keys:
                keys.append((c.key, c.label))
    gaps = [c["category"] for c in cov if c["gap"]]
    top_unknown: dict[str, int] = {}
    for e in evals:
        if e.decision != "EXCLUDED":
            for c in e.unknown:
                top_unknown[c.label] = top_unknown.get(c.label, 0) + 1
    top3 = sorted(top_unknown.items(), key=lambda x: -x[1])[:3]

    strip = f"""<div class="strip">
 <div><span>조건 추출</span><b>{len({p.field for p in req.provenance})}개 항목</b><em>{('누락: ' + ', '.join(req.missing())) if req.missing() else '핵심 항목 모두 추출'}</em></div>
 <div><span>후보 판정</span><b>적격 {n['ELIGIBLE']} · 보류 {n['HOLD']} · 제외 {n['EXCLUDED']}</b><em>미확인은 충족으로 보지 않음</em></div>
 <div><span>가장 많이 막힌 곳</span><b>{E(top3[0][0]) if top3 else '-'}</b><em>{', '.join(f'{E(k)} {v}건' for k, v in top3)}</em></div>
 <div><span>다음 행동</span><b>{'후보 발굴: ' + ', '.join(gaps) if gaps else '공급사 견적 회신 비교'}</b><em>견적 요청 초안 {len(rfqs)}건 준비 (미발송)</em></div>
</div>"""

    prov_rows = "".join(
        f"<tr><th>{E(LABELS.get(p.field, p.field))}</th><td>{E(_val(p.field, p.value))}</td><td class='q'>{E(p.quote)}</td><td><span class='src'>{E(p.source)}</span></td></tr>"
        for p in req.provenance)

    cov_rows = "".join(
        f"<tr><th>{E(c['category'])} {c['need']}종</th><td><div class='bar'>"
        + "".join(f"<i class='{cls}' style='flex:{c[k]}' title='{lbl} {c[k]}'></i>" for k, cls, lbl in
                  (("eligible", "ok", "적격"), ("hold", "hold", "보류"), ("excluded", "ex", "제외")) if c[k])
        + f"</div></td><td>적격 {c['eligible']} · 보류 {c['hold']} · 제외 {c['excluded']}</td><td>{'<b class=gap>후보 부족</b>' if c['gap'] else '후보 확보'}</td></tr>"
        for c in cov)

    def cell(e: Evaluation, key: str) -> str:
        c = next((x for x in e.checks if x.key == key), None)
        if not c:
            return "<td>-</td>"
        ic, cls, lbl = ICON[c.status]
        tip = E(f"{lbl} · 기준 {c.expected} · 실제 {c.actual or '없음'} {('· ' + c.note) if c.note else ''}")
        return f"<td class='c {cls}' title='{tip}'>{ic}</td>"

    mrows = []
    for e in evals:
        c = e.candidate
        d, dcls = DEC[e.decision]
        price = f"{c.observed_price:,}원" if c.observed_price else "미수집"
        notes = " · ".join(c.notes)
        name = f"<a href='{E(c.url)}' target='_blank' rel='noopener'>{E(c.name)}</a>" if c.url else E(c.name)
        sample = " <span class='src'>예시</span>" if c.is_sample else ""
        mrows.append(f"<tr><td><span class='dec {dcls}'>{d}</span></td><td class='nm'>{name}{sample}<small>{E(c.supplier)} · {E(c.option or '옵션 미확인')}</small>"
                     f"{f'<small class=nt>{E(notes)}</small>' if notes else ''}</td><td class='cat'>{E(c.category or '-')}</td><td class='num'>{price}<small>{E(c.price_kind)}</small></td>"
                     + "".join(cell(e, k) for k, _ in keys) + "</tr>")
    mhead = "".join(f"<th class='c'>{E(lbl)}</th>" for _, lbl in keys)

    cost_html = ""
    if cost:
        crow = "".join(f"<tr><th>{E(l.label)}</th><td class='num'>{f'{l.amount:,}원' if l.amount is not None else '<span class=unkt>미확인</span>'}</td><td>{E(l.basis)}</td></tr>" for l in cost.lines)
        res = (f"<b>{cost.residual:,}원</b> (모든 항목 입력됨 — 입력값 기준)" if cost.residual is not None
               else f"<b class='unkt'>확정 불가</b> — 미확인 {len(cost.unknown)}개 (미확인 ≠ 0원)")
        scen = "".join(f"<tr><td>{E(s['candidate'])}</td><td class='num'>{s['assumed_supply']:,}원</td>"
                       f"<td class='num {'neg' if s['gap_before_other_costs'] < 0 else ''}'>{s['gap_before_other_costs']:+,}원</td><td>{E(s['verdict'])}</td></tr>"
                       for s in cost.scenarios)
        cost_html = f"""<section><h2>⑤ 1인 비용 구조</h2>
<p class="formula">{f'{cost.budget_per_person:,}원' if cost.budget_per_person else '1인 예산'} − 매입 − 포장 − 배송 − 운영·CS − 구축비 배분 − 기타 = 잔여액 → {res}</p>
<table><tbody>{crow}</tbody></table>
{f'<h3>가정 시나리오: 공개 판매가를 매입가로 가정</h3><table><thead><tr><th>후보</th><th>가정 매입가</th><th>추가비용 전 차액</th><th>판단</th></tr></thead><tbody>{scen}</tbody></table>' if scen else ''}
<ul class="notes">{''.join(f'<li>{E(x)}</li>' for x in cost.notes)}</ul></section>"""

    rfq_html = "".join(
        f"<details><summary><b>{E(r['supplier'])}</b> · 후보 {len(r['items'])}개 <span class='src'>{E(r['status'])}</span></summary>"
        f"<pre>{E(r['body'])}</pre><ol>{''.join(f'<li>{E(q)}</li>' for q in r['common'])}</ol>"
        + "".join(f"<p><b>{E(i['name'])}</b> ({E(i['option'] or '옵션 미확인')})</p><ul>{''.join(f'<li>{E(q)}</li>' for q in i['questions'])}</ul>" for i in r["items"])
        + "</details>" for r in rfqs)

    title = req.title or req.bid_id or "임직원 선물 입찰"
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)} 분석</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css">
<style>
:root{{--ink:#172635;--mut:#5a6875;--line:#dae1e8;--bg:#f4f6f9;--ok:#1f7a4a;--hold:#a86b00;--ex:#b42318}}
body{{font-family:"Pretendard Variable",system-ui,sans-serif;background:var(--bg);color:var(--ink);margin:0;line-height:1.65;font-size:14.5px}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 20px 60px}}
h1{{font-size:26px;margin:4px 0;letter-spacing:-.02em}} .meta{{color:var(--mut)}}
.banner{{background:#fff4d9;border-radius:10px;padding:10px 14px;margin:14px 0;font-size:13.5px}}
.strip{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}}
.strip div{{background:#fff;border-radius:12px;padding:14px;border:1px solid var(--line)}}
.strip span{{display:block;font-size:12px;color:var(--mut)}} .strip b{{display:block;font-size:16px;margin:2px 0}} .strip em{{font-style:normal;font-size:12.5px;color:var(--mut)}}
section{{background:#fff;border-radius:12px;padding:20px 22px;margin:14px 0;border:1px solid var(--line)}}
h2{{font-size:18px;margin:0 0 12px}} h3{{font-size:15px;margin:18px 0 8px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}} th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}}
thead th{{background:#edf3f7;font-weight:650;position:sticky;top:0}}
td.q{{color:var(--mut);font-size:12.5px}} .src{{font-size:11px;background:#eef1f4;border-radius:6px;padding:1px 6px;color:var(--mut);white-space:nowrap}}
.bar{{display:flex;height:12px;border-radius:6px;overflow:hidden;background:#eef1f4;min-width:160px}} .bar i.ok{{background:var(--ok)}} .bar i.hold{{background:#f0b429}} .bar i.ex{{background:#e4a4a0}}
.gap{{color:var(--ex)}} .scroll{{overflow-x:auto}}
th.c,td.c{{text-align:center;white-space:nowrap}} td.c.pass{{color:var(--ok)}} td.c.fail{{color:var(--ex);font-weight:800}} td.c.unk{{color:var(--hold);font-weight:700}}
.dec{{font-size:12px;font-weight:700;border-radius:999px;padding:2px 9px;white-space:nowrap}} .dec.ok{{background:#e3f4ea;color:var(--ok)}} .dec.hold{{background:#fff1d1;color:var(--hold)}} .dec.ex{{background:#fde8e6;color:var(--ex)}}
td.nm{{min-width:280px}} td.nm small{{display:block;color:var(--mut);font-size:12px}} td.cat{{white-space:nowrap}} td.nm small.nt{{color:var(--hold)}} td.num{{white-space:nowrap;text-align:right}} td.num small{{display:block;color:var(--mut);font-size:11px}}
.num.neg{{color:var(--ex);font-weight:700}} .unkt{{color:var(--hold);font-weight:700}} .formula{{background:#f7f9fb;border-radius:8px;padding:10px 12px}}
details{{border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:8px 0}} pre{{white-space:pre-wrap;font-family:inherit;background:#f7f9fb;padding:10px;border-radius:8px}}
.legend{{font-size:12.5px;color:var(--mut)}} a{{color:#1263a4}}
@media (max-width:820px){{.strip{{grid-template-columns:1fr 1fr}}}}
@media print{{body{{background:#fff}} section{{break-inside:avoid}}}}
</style></head><body><div class="wrap">
<div class="meta">{today.isoformat()} · 내부 검토용 · commerce_ai B2B</div>
<h1>{E(title)} — 후보·조건 분석</h1>
<div class="banner">조사 후보이며 최종 추천·계약 가능·온라인 최저가 검증 완료를 의미하지 않습니다. 공개 판매가는 견적이 아니며, 견적 요청은 발송되지 않았습니다.</div>
{strip}
<section><h2>① 추출한 조건 (원문 발췌)</h2><table><thead><tr><th>항목</th><th>값</th><th>원문</th><th>출처</th></tr></thead><tbody>{prov_rows}</tbody></table></section>
<section><h2>② 카테고리 충족도</h2><table><tbody>{cov_rows}</tbody></table></section>
<section><h2>③ 후보 × 확인 항목</h2><p class="legend">● 충족 · ? 미확인 · ✕ 위반 — 칸에 마우스를 올리면 기준·실제값이 보입니다. 미확인이 하나라도 있으면 '보류', 위반이 있으면 '제외'.</p>
<div class="scroll"><table><thead><tr><th>판정</th><th>후보</th><th>분류</th><th>관측가</th>{mhead}</tr></thead><tbody>{''.join(mrows)}</tbody></table></div></section>
{cost_html}
<section><h2>⑥ 공급사별 견적 요청 초안 — 발송 전 검토</h2><p class="legend">마감된 공고를 참고한 공급 가능성 조사입니다. 실제 발주나 확보 물량으로 표현하지 않습니다.</p>{rfq_html or '<p>보류 후보 없음</p>'}</section>
<section><h2>⑦ 판단 규칙</h2><ol>
<li>공고 필수조건과 상품·옵션별 근거를 먼저 대조합니다. 미확인은 충족으로 간주하지 않습니다.</li>
<li>품절 공지가 있는 옵션은 보류, 지연 공지는 도착 기한 재확인 근거로 씁니다.</li>
<li>가격 적용 단위가 불명확하면 단가 환산·총액 계산을 하지 않습니다.</li>
<li>상품비·포장·배송·기타 비용을 합산하되 포함 비용을 중복 계산하지 않습니다. 미확인 비용은 0원이 아닙니다.</li>
<li>공개 가격·공급사 견적·확정 거래가를 따로 보존하고, 수량·지역·포장·유효기간이 바뀌면 재확인합니다.</li></ol></section>
</div></body></html>"""
