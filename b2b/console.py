"""B2B 프롬프트 콘솔 — 자연어 지시 → 도구 실행 → 결과 블록.

도구: list_bids · collect · trends · import_bids · analyze · discover · cost · rfq · report · proposal · help
(B2B gift-monitor 와 gift_trend_analyzer 기능은 collect · list_bids · trends · analyze 로 통합)
라우팅은 키워드 규칙이 기본 (LLM 불필요). 작업 상태(현재 공고·조건·판정·비용)는 워크스페이스에 유지되어
"견적 요청서 만들어줘", "제안서 작성해줘" 처럼 짧게 이어서 지시할 수 있다.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from b2b import bids as bidstore
from b2b import costing, evidence, proposal, report, rfq, sourcing
from b2b.gift_monitor import checkpoints, collectors, trends
from b2b.models import BidRequirement, Evaluation
from b2b.request_parser import parse_with_llm
from shared.config import ROOT, get_settings

DOCS = ROOT / "var" / "docs"


@dataclass
class Workspace:
    id: str
    bid_id: str | None = None
    req: BidRequirement | None = None
    evals: list[Evaluation] = field(default_factory=list)
    cost_inputs: dict = field(default_factory=dict)
    mall_build_total: int | None = None
    cost: costing.CostAnalysis | None = None
    docs: dict = field(default_factory=dict)


ROUTES = [
    ("proposal", r"제안서"),
    ("rfq", r"견적|RFQ|요청서"),
    ("report", r"리포트|보고서|분석\s*결과\s*(?:열|보)"),
    ("cost", r"비용|원가|마진|매입가|잔여"),
    ("discover", r"후보\s*(?:더|추가)?\s*(?:찾|발굴|탐색)|소싱|탐색"),
    ("trends", r"트렌드|동향|통계|분포"),
    ("collect", r"수집|크롤|나라장터"),
    ("import_bids", r"가져와|동기화|새로\s*고침|불러와|import"),
    ("list_bids", r"공고\s*(?:목록|리스트|보여)|새\s*공고|목록|입찰중|마감\s*임박|모니터"),
    ("help", r"^(?:도움|help|\?|뭐\s*할\s*수)"),
]


class Console:
    def __init__(self):
        evidence.all_candidates()  # 최초 실행 시 번들 적재
        bidstore.ensure_seed()
        self.ws: dict[str, Workspace] = {}

    def workspace(self, wid: str | None) -> Workspace:
        if wid and wid in self.ws:
            return self.ws[wid]
        w = Workspace(id=wid or uuid.uuid4().hex[:10])
        self.ws[w.id] = w
        return w

    # ── 진입점 ────────────────────────────────────────────────
    def run(self, wid: str | None, prompt: str, today: date | None = None) -> dict:
        w = self.workspace(wid)
        p = (prompt or "").strip()
        action = next((a for a, rx in ROUTES if re.search(rx, p, re.IGNORECASE)), "analyze")
        # 공고번호가 있거나 숫자 조건이 섞여 있으면 분석 우선 (단, 제안서·견적 지시는 유지)
        if action in ("list_bids", "help") and re.search(r"\d+\s*명|1인당|[A-Za-z가-힣]+-\d{6,}|(?:G2B|legacy|bid)-[\w-]+", p):
            action = "analyze"
        if action in ("rfq", "proposal", "report", "cost", "discover") and w.req is None:
            pre = self._analyze(w, p, today)
            if w.req is None:
                return self._out(w, action, pre)
        handler = getattr(self, "_" + action)
        blocks = handler(w, p, today)
        return self._out(w, action, blocks)

    def _out(self, w: Workspace, action: str, blocks: list[dict]) -> dict:
        return {"workspace_id": w.id, "action": action, "bid_id": w.bid_id, "blocks": blocks}

    # ── 도구 ──────────────────────────────────────────────────
    def _help(self, w, p, today):
        return [{"type": "text", "md": "이렇게 지시할 수 있어요."},
                {"type": "actions", "items": ["나라장터 공고 수집해줘", "입찰중 공고 보여줘", "입찰 트렌드 분석해줘",
                                              "공고 목록 보여줘", "IBK서비스-2026008 분석해줘",
                                              "직원 500명 1인당 5만원 식품 2종 생활용품 1종 3영업일 배송 조건 분석",
                                              "매입가 36000 포장 1500 배송 3500 운영 800 구축비 300만원으로 비용 계산",
                                              "견적 요청서 만들어줘", "제안서 작성해줘"]}]

    def _list_bids(self, w, p, today):
        want = "입찰중" if "입찰중" in p else "마감임박" if re.search(r"마감\s*임박", p) else None
        show_legacy = bool(re.search(r"전체|기존|미검증", p))
        rows = []
        hidden = 0
        for b in bidstore.list_bids():
            v = b.view(today)
            if want and v["status"] != want:
                continue
            if b.verification == "legacy_unverified" and not show_legacy:
                hidden += 1
                continue
            rows.append({"bid_id": b.bid_id, "title": b.title, "agency": b.agency, "deadline": b.deadline,
                         "status": v["status"], "bid_type": v["bid_type"], "verification": b.verification,
                         "verification_label": v["verification_label"], "url": b.url,
                         "budget": b.budget or (b.requirement.computed_total() if b.requirement else None),
                         "headcount": v["headcount"], "source": b.source, "tags": b.tags})
        order = {"마감임박": 0, "입찰중": 1, "마감일 미확인": 2, "입찰마감": 3}
        rows.sort(key=lambda r: order.get(r["status"], 9))
        msg = f"{'‘' + want + '’ ' if want else ''}공고 **{len(rows)}건**입니다."
        if hidden:
            msg += f" 미검증 기존 데이터 {hidden}건은 숨겼어요 ('기존 공고 전체 보여줘'로 확인)."
        return [{"type": "text", "md": msg}, {"type": "bid_list", "rows": rows},
                {"type": "actions", "items": [f"{r['bid_id']} 분석해줘" for r in rows[:3]] + ["나라장터 공고 수집해줘"]}]

    def _collect(self, w, p, today):
        m = re.search(r"(\d+)\s*일", p)
        res = collectors.collect_all(days=int(m.group(1)) if m else 14)
        log = [line for r in res["results"] for line in r["log"]]
        blocks = [{"type": "text", "md": f"수집을 마쳤어요. 신규 **{res['new']}건** (조회된 고유 공고 {res['found']}건)."},
                  {"type": "log", "lines": log}]
        return blocks + self._list_bids(w, "입찰중" if res["new"] else p, today)[1:]

    def _trends(self, w, p, today):
        legacy = bool(re.search(r"기존|미검증|전체\s*데이터", p))
        t = trends.analyze(include_unverified=True, include_legacy=legacy, today=today)
        return [{"type": "text", "md": f"입찰 트렌드를 집계했어요 (대상 {t['total']}건)."},
                {"type": "trends", **t},
                {"type": "actions", "items": ["입찰중 공고 보여줘", "기존 데이터 포함해서 트렌드 보여줘"]}]

    def _import_bids(self, w, p, today):
        url = get_settings().b2b_bid_source_url
        if not url:
            return [{"type": "notice", "tone": "warn",
                     "md": "B2B_BID_SOURCE_URL 이 설정되지 않았습니다. smallbiz-monitor 의 공고 JSON 주소를 .env 에 넣거나, 위의 '공고 파일 올리기'로 CSV/JSON 을 올려 주세요."}]
        try:
            n = bidstore.fetch_remote(url)
        except Exception as e:
            return [{"type": "notice", "tone": "warn", "md": f"가져오기 실패: {e}"}]
        return [{"type": "text", "md": f"공고 **{n}건**을 가져왔습니다."}] + self._list_bids(w, p, today)

    def _analyze(self, w, p, today):
        m = re.search(r"(?:G2B|legacy|bid)-[\w-]+|[A-Za-z가-힣]+-\d{6,8}", p)
        base, bid = None, None
        if m and (bid := bidstore.get(m.group(0))):
            base, w.bid_id = bid.requirement, bid.bid_id
        elif w.req and not m:
            base = w.req  # 이어서 조건 수정 ("배송 3영업일로 바꿔")
        req = parse_with_llm(p, base)
        pre: list[dict] = []
        if bid:
            v = bid.view(today)
            pre.append({"type": "bid_card", **v})
            if not v["trusted"]:
                pre.append({"type": "notice", "tone": "warn",
                            "md": f"이 공고는 **{v['verification_label']}** 상태입니다. 아래 결과는 원문과 대조하기 전 참고용이에요."
                                  + (" 기존 smallbiz-monitor 시드 데이터라 실제 공고인지부터 확인이 필요합니다." if bid.verification == "legacy_unverified" else "")})
            pre.append({"type": "checkpoints", **checkpoints.checkpoints(bid.title, bid.summary)})
        if not (req.headcount or req.budget_per_person or req.categories):
            if bid:
                return pre + [{"type": "notice", "tone": "warn",
                               "md": "공고 본문에 인원·1인 예산·품목 구성이 없어 후보 판정과 비용 분석은 하지 않았어요. 입찰 모니터에서 제안요청서(HWPX·PDF·DOCX)를 첨부하면 조건을 다시 추출합니다."},
                              {"type": "actions", "items": ["입찰중 공고 보여줘", "입찰 트렌드 분석해줘"]}]
            return [{"type": "text", "md": "분석할 공고나 조건을 찾지 못했어요. 공고번호를 말하거나 공고 조건(인원·1인 예산·품목·배송 기한)을 붙여 넣어 주세요."},
                    *self._help(w, p, today)[1:]]
        w.req = req
        w.bid_id = req.bid_id or w.bid_id
        w.evals = evidence.evaluate_all(req, today=today)
        cov = sourcing.coverage(req, w.evals)
        discovered = 0
        if any(c["gap"] for c in cov):
            discovered = len(sourcing.discover(req, [c["category"] for c in cov if c["gap"]]))
            w.evals = evidence.evaluate_all(req, today=today)
            cov = sourcing.coverage(req, w.evals)
        w.cost = self._calc_cost(w)
        blocks = pre + [
            {"type": "text", "md": f"**{req.title or req.bid_id or '입력 조건'}** 조건을 추출하고 후보 {len(w.evals)}개를 판정했어요."
                                   + (f" 후보가 부족한 카테고리는 마켓 검색으로 {discovered}개를 더 찾았어요." if discovered else "")},
            {"type": "requirement", "rows": [{"field": pv.field, "value": str(pv.value), "quote": pv.quote, "source": pv.source}
                                             for pv in req.provenance], "missing": req.missing(),
             "total": req.computed_total()},
            {"type": "coverage", "rows": cov},
            self._cand_block(w.evals),
            self._cost_block(w.cost),
            {"type": "actions", "items": ["견적 요청서 만들어줘", "분석 리포트 열어줘", "제안서 작성해줘",
                                          "매입가 36000 포장 1500 배송 3500 운영 800 구축비 300만원으로 비용 계산"]},
        ]
        return blocks

    def _discover(self, w, p, today):
        cats = [c for c in ("식품", "건강기능식품", "생활용품") if c in p] or None
        n = len(sourcing.discover(w.req, cats))
        w.evals = evidence.evaluate_all(w.req, today=today)
        return [{"type": "text", "md": f"마켓 검색으로 후보 {n}개를 추가/갱신했어요. 모두 공개 판매가 관측이므로 보류(HOLD)에서 시작합니다."},
                {"type": "coverage", "rows": sourcing.coverage(w.req, w.evals)}, self._cand_block(w.evals)]

    def _cost(self, w, p, today):
        t = p.replace(",", "")
        keymap = {"supply": r"(?:매입가|매입|공급가|상품비)", "packaging": r"포장", "shipping": r"배송",
                  "ops_cs": r"(?:운영|CS)", "other": r"기타"}
        for k, rx in keymap.items():
            if m := re.search(rx + r"\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(만)?\s*원?", t):
                w.cost_inputs[k] = int(float(m.group(1)) * (10000 if m.group(2) else 1))
        if m := re.search(r"구축(?:비)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(만)?\s*원?", t):
            w.mall_build_total = int(float(m.group(1)) * (10000 if m.group(2) else 1))
        w.cost = self._calc_cost(w)
        return [{"type": "text", "md": "비용 구조를 다시 계산했어요. 입력하지 않은 항목은 '미확인'으로 남겨 잔여액을 확정하지 않습니다."},
                self._cost_block(w.cost)]

    def _rfq(self, w, p, today):
        drafts = rfq.drafts(w.req, [e for e in w.evals if not e.candidate.is_sample])
        return [{"type": "text", "md": f"공급사별 견적 요청 초안 **{len(drafts)}건**입니다. 자동 발송하지 않아요 — 검토 후 직접 보내세요."},
                {"type": "rfq", "drafts": drafts}]

    def _report(self, w, p, today):
        html_ = report.render(w.req, w.evals, sourcing.coverage(w.req, w.evals), w.cost,
                              rfq.drafts(w.req, [e for e in w.evals if not e.candidate.is_sample]), today)
        name = self._save(w, "report", html_, "html")
        return [{"type": "text", "md": "분석 리포트를 만들었어요."},
                {"type": "docs", "items": [{"label": "분석 리포트 (HTML)", "href": f"/files/{name}"}]}]

    def _proposal(self, w, p, today):
        pf = proposal.load_profile()
        bid = bidstore.get(w.bid_id) if w.bid_id else None
        src_status = None
        if bid and bid.verification not in bidstore.TRUSTED:
            src_status = bidstore.VERIFICATION_LABEL.get(bid.verification, bid.verification)
        items = []
        todo = 0
        for mode, label in (("internal", "내부 검토본"), ("external", "제출본 초안")):
            prop = proposal.build(w.req, w.evals, profile=pf, cost=w.cost, mode=mode, today=today,
                                  polish="다듬" in p or "polish" in p, source_status=src_status)
            todo = prop.todo_count
            h = self._save(w, f"proposal_{mode}", proposal.to_html(prop), "html")
            d = f"{w.id}_proposal_{mode}.docx"
            proposal.to_docx(prop, DOCS / d)
            # PPTX
            pptx_name = f"{w.id}_proposal_{mode}.pptx"
            try:
                proposal.to_pptx(prop, DOCS / pptx_name)
                pptx_ok = True
            except Exception:
                pptx_ok = False
            # HWPX
            hwpx_name = f"{w.id}_proposal_{mode}.hwpx"
            try:
                proposal.to_hwpx(prop, DOCS / hwpx_name)
                hwpx_ok = True
            except Exception:
                hwpx_ok = False

            items += [
                {"label": f"제안서 {label} (HTML·인쇄)", "href": f"/files/{h}"},
                {"label": f"제안서 {label} (Word)", "href": f"/files/{d}"},
            ]
            if pptx_ok:
                items.append({"label": f"제안서 {label} (PowerPoint)", "href": f"/files/{pptx_name}"})
            if hwpx_ok:
                items.append({"label": f"제안서 {label} (HWPX)", "href": f"/files/{hwpx_name}"})
        outline = [s.title for s in prop.sections]
        return [{"type": "text", "md": f"제안서 초안을 만들었어요. 확인되지 않은 값은 지어내지 않고 **[확인 필요]** {todo}곳으로 남겼어요 (노란 표시)."},
                {"type": "outline", "items": outline},
                {"type": "docs", "items": items},
                {"type": "notice", "tone": "info",
                 "md": "회사명·실적·플랫폼 등은 b2b/data/company_profile.json 을 채우면 자동 반영됩니다. 제출본 초안에는 원가·마진·내부 판정이 들어가지 않아요."}]

    # ── 보조 ──────────────────────────────────────────────────
    def _calc_cost(self, w: Workspace) -> costing.CostAnalysis:
        # 가정 시나리오는 단위가 분명한 공개 판매가만 사용 (단위 미확인·공급표 가격 제외)
        floor = w.req.min_online_price or 0
        proxies = [e.candidate for e in w.evals if e.decision == "HOLD" and e.candidate.observed_price
                   and e.candidate.observed_price >= floor and not e.candidate.is_sample
                   and e.candidate.price_kind in ("public_retail", "public_option_unconfirmed")][:4]
        return costing.analyze(w.req, w.cost_inputs, proxies, w.mall_build_total)

    @staticmethod
    def _cand_block(evals: list[Evaluation]) -> dict:
        rows = []
        for e in evals:
            c = e.candidate
            rows.append({"decision": e.decision, "name": c.name, "supplier": c.supplier, "category": c.category,
                         "option": c.option, "price": c.observed_price, "price_kind": c.price_kind, "url": c.url,
                         "is_sample": c.is_sample, "notes": c.notes,
                         "failed": [x.label for x in e.failed], "unknown": [x.label for x in e.unknown],
                         "checks": [{"label": x.label, "status": x.status, "expected": str(x.expected or ""),
                                     "actual": str(x.actual or ""), "note": x.note} for x in e.checks]})
        return {"type": "candidates", "rows": rows}

    @staticmethod
    def _cost_block(cost: costing.CostAnalysis | None) -> dict:
        if not cost:
            return {"type": "notice", "md": "비용 분석 없음"}
        return {"type": "cost", "budget": cost.budget_per_person, "lines": [l.model_dump() for l in cost.lines],
                "known_total": cost.known_total, "unknown": cost.unknown, "residual": cost.residual,
                "scenarios": cost.scenarios, "notes": cost.notes}

    @staticmethod
    def _save(w: Workspace, kind: str, content: str, ext: str) -> str:
        DOCS.mkdir(parents=True, exist_ok=True)
        name = f"{w.id}_{kind}.{ext}"
        Path(DOCS / name).write_text(content, encoding="utf-8")
        w.docs[kind] = name
        return name
