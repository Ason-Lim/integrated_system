"""공고 유형별 점검 포인트 + 제안 준비도 자가 점검.

gift_trend_analyzer 의 generate_ai_analysis()(요구사항·전략·리스크 문구)와 evaluator.html(100점 시뮬레이터)을 이식.
바꾼 점
  - 'AI 분석'이 아니라 유형별 일반 체크포인트(규칙)임을 명시
  - 특정 브랜드 추천·'2시간 이내 재발송 보장' 같은 근거 없는 약속 문구 제거
  - 배점은 '예시 배점'. 공고 평가표가 있으면 weights 를 그 값으로 바꿔 계산
"""
from __future__ import annotations

import re

from b2b.gift_monitor import classify

COMMON_PHYSICAL = {
    "requirements": ["선택형 구성과 1인 1선택 운영 방식", "전국 개별 주소 배송망과 신선·보냉 포장",
                     "서류 통과 후 견본품 제출·품평회 대응", "파손·오배송·하자 시 교환·회수 절차"],
    "risks": ["명절 물류 집중기 배송 지연", "부재 시 신선식품 방치로 인한 민원"],
}
BY_TYPE = {
    "온누리상품권": {
        "requirements": ["온누리상품권 판매·조달 대행 자격 증빙", "지류형 일련번호 관리와 배송 유실 방지",
                         "모바일·카드형 등록·충전 안내", "본사·지사 배부와 수령 확인 방법"],
        "strategies": ["판매 대행 자격 증빙을 앞쪽에 배치", "지역경제·전통시장 상생 효과를 사업 목적과 연결",
                       "분실·미수령 처리 절차를 구체적으로 제시"],
        "risks": ["수령 누락에 따른 민원", "등기 배송 비용 증가와 반송 처리", "모바일 등록이 어려운 임직원 지원 부족"],
    },
    "모바일상품권": {
        "requirements": ["대량·예약 발송 시스템과 재발송 처리", "선택형 교환처(백화점·외식·카페 등) 구성",
                         "미수신·번호 변경·오발송 대응 창구", "발송·교환 현황 보고"],
        "strategies": ["임직원이 직접 고르는 선택 화면과 사용 편의성 제시", "재발송·CS 처리 기준을 수치로 약속할 수 있는 범위에서 제시",
                       "교환처 제휴 증빙 첨부"],
        "risks": ["스팸 차단으로 인한 미수신", "유효기간 만료·환불 기준 불명확", "교환처 서비스 중단"],
    },
    "선물세트 (육류)": {
        "requirements": ["축산물 가공·포장 관련 영업 허가와 위생 인증", "냉장·냉동 유통 온도 관리 증빙", "등급판정확인서 등 원산지·등급 증빙"],
        "strategies": ["등급·원산지 증빙을 필수 첨부로 제시", "보냉 포장 사양과 배송 중 온도 유지 방법 제시"],
        "risks": ["배송 중 해동·변질", "부재 시 방치로 인한 품질 민원"],
    },
    "선물세트 (과일/농산물)": {
        "requirements": ["산지 직송·선별 체계", "GAP 등 인증 여부", "충격 방지 포장"],
        "strategies": ["선별 기준(중량·과수·당도 측정 여부)을 측정 방법과 함께 제시", "작황 변동 시 동급 대체 기준을 미리 합의"],
        "risks": ["작황·기후에 따른 품질 편차와 물량 부족", "운송 중 눌림·흠집"],
    },
    "선물세트 (생선/수산물)": {
        "requirements": ["원산지 증명과 이력 관리", "냉동·염장 위생 관리", "밀봉·보냉 포장"],
        "strategies": ["원산지 증빙과 이력 추적 방법 제시", "포장 사양을 사진·도식으로 제시"],
        "risks": ["온도 일탈에 따른 신선도 저하", "포장 파손 시 냄새 민원"],
    },
    "선물세트 (가전제품)": {
        "requirements": ["KC 인증", "무상 A/S 기간과 서비스망", "초기 불량 교환 절차"],
        "strategies": ["A/S 접수 경로와 지역별 처리 방법 제시", "초기 불량 교환 기준 명시"],
        "risks": ["배송 중 파손·초기 불량", "지방 거주 임직원의 A/S 불편"],
    },
    "선물세트 (주방기구/생활용품)": {
        "requirements": ["정품·유통 권한 증빙", "파손 방지 포장"],
        "strategies": ["정품 유통 경로 증빙 첨부", "구성·포장 사진 제시"],
        "risks": ["식기·유리류 파손 반품", "시중가 대비 가격 경쟁력 평가"],
    },
    "선물세트 (건강식품/기타)": {
        "requirements": ["건강기능식품 판매업 신고", "기능성 표시·인정 사항 확인", "유통기한 관리"],
        "strategies": ["연령·선호별 선택지를 넓힌 구성", "유통기한 잔여 기준을 명시"],
        "risks": ["유통기한 임박 제품 배송", "섭취 이상 호소 시 보상 기준 미비"],
    },
}


def checkpoints(title: str, text: str = "") -> dict:
    t = classify.bid_type(title, text)
    spec = BY_TYPE.get(t, {})
    req = list(spec.get("requirements", []))
    risks = list(spec.get("risks", []))
    if t.startswith("선물세트"):
        req += COMMON_PHYSICAL["requirements"]
        risks += COMMON_PHYSICAL["risks"]
    qty = re.search(r"(약\s*\d[\d,]*\s*명|\d[\d,]*\s*명|\d[\d,]*\s*세트)", text or "")
    return {
        "bid_type": t, "company_type": classify.company_type(title, text),
        "qualifications": classify.qualifications(title, text), "scale": qty.group(1) if qty else None,
        "requirements": req, "strategies": spec.get("strategies", []), "risks": risks,
        "basis": "공고 유형별 일반 체크포인트 (키워드 규칙). 실제 요구사항은 공고 원문·제안요청서로 확인하세요.",
    }


# ── 제안 준비도 자가 점검 (evaluator.html 이식) ─────────────────
EVAL_ITEMS = [
    # key, 영역, 항목, 예시 배점, 선택지(라벨, 비율)
    ("credit", "정량", "신용평가 등급", 10, [("A 이상", 1.0), ("BBB", 0.8), ("BB 이하", 0.5), ("미보유", 0.0)]),
    ("performance", "정량", "유사 납품 실적", 10, [("3건 이상", 1.0), ("1~2건", 0.7), ("없음", 0.2)]),
    ("certification", "정량", "관련 인증 (HACCP·ISO 등)", 10, [("2개 이상", 1.0), ("1개", 0.7), ("없음", 0.3)]),
    ("quality", "정성", "상품 구성·품질", 20, [("견본 준비·증빙 완비", 1.0), ("후보 확정, 증빙 일부", 0.7), ("후보 검토 중", 0.4)]),
    ("price", "정성", "가격 경쟁력", 15, [("견적 확보·예산 내", 1.0), ("공개가 기준 추정", 0.5), ("미확인", 0.2)]),
    ("logistics", "정성", "배송·물류", 15, [("기한 확약서 확보", 1.0), ("공급사 구두 확인", 0.6), ("미확인", 0.2)]),
    ("cs", "CS·IT", "CS 운영", 10, [("전담 창구·시간 명시", 1.0), ("겸임 운영", 0.6), ("미정", 0.2)]),
    ("system", "CS·IT", "폐쇄몰·발송 시스템", 10, [("자체 운영", 1.0), ("임대 솔루션 계약", 0.8), ("미정", 0.2)]),
]


def eval_form() -> dict:
    return {"items": [{"key": k, "area": a, "label": l, "weight": w, "options": [o[0] for o in opts]}
                      for k, a, l, w, opts in EVAL_ITEMS],
            "note": "예시 배점입니다. 공고 평가표가 있으면 항목별 배점을 그 값으로 바꿔 계산하세요."}


def evaluate(answers: dict[str, str], weights: dict[str, float] | None = None) -> dict:
    weights = weights or {}
    rows, total, maxsum, missing = [], 0.0, 0.0, []
    for k, area, label, w, opts in EVAL_ITEMS:
        w = float(weights.get(k, w))
        maxsum += w
        ratio = dict(opts).get(answers.get(k, ""))
        if ratio is None:
            missing.append(label)
            rows.append({"key": k, "area": area, "label": label, "weight": w, "score": None})
            continue
        s = round(w * ratio, 1)
        total += s
        rows.append({"key": k, "area": area, "label": label, "weight": w, "score": s, "answer": answers[k]})
    answered_max = sum(r["weight"] for r in rows if r["score"] is not None)
    pct = round(total * 100 / answered_max) if answered_max else 0   # 응답한 항목 기준
    weak = sorted((r for r in rows if r["score"] is not None and r["score"] < r["weight"] * 0.7),
                  key=lambda r: r["score"] - r["weight"])[:3]
    grade = "준비 양호" if pct >= 85 else "보완 후 참여" if pct >= 70 else "핵심 요건 보강 필요"
    if missing:
        grade += f" (미응답 {len(missing)}개 — 확정 아님)"
    return {"score": round(total, 1), "max": maxsum, "answered_max": answered_max, "pct": pct, "grade": grade, "rows": rows, "missing": missing,
            "weak": [r["label"] for r in weak],
            "note": "제안 준비도 자가 점검이며 낙찰 가능성 예측이 아닙니다. 응답하지 않은 항목은 0점이 아니라 '미응답'으로 표시합니다."}
