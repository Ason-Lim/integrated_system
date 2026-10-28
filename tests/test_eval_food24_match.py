"""매칭 평가 판정 — 매칭 코드의 정규화에 기대지 않고 구분자·이름·제조사·원재료를 따로 본다."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ev", ROOT / "scripts" / "eval_food24_match.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def r(no, name, company="(주)서흥", raw="A", **kw):
    return {"report_no": no, "name": name, "company": company, "raw": raw, "company_matched": True, **kw}


def test_verdicts():
    src = r("1", "락티스 (100B)")
    assert ev.judge(src, r("1", "락티스 (100B)"))[0] == "정답"
    assert ev.judge(src, r("2", "락티스 (0.1B)"))[0] == "오연결(구분자 다름)"
    assert ev.judge(r("1", "밀크씨슬+"), r("2", "밀크씨슬"))[0] == "오연결(이름 다름)"
    assert ev.judge(r("1", "밀크씨슬"), r("2", "밀크씨슬", company="(주)노바렉스"))[0] == "오연결(제조사 다름)"
    assert ev.judge(r("1", "밀크씨슬"), r("2", "밀크씨슬", raw_capsule="젤라틴"))[0] == "오연결(원재료 다름)"
    assert ev.judge(r("1", "밀크씨슬", company="동서바이오팜(주)"),
                    r("2", "밀크씨슬", company="동서바이오팜(주) 안성공장"))[0] == "판단불가(동일 내용 재신고)"
    assert ev.judge(r("1", "골든에센셜(Golden Essential)"), r("2", "골든 에센셜"))[0] == "판단불가(괄호 번역 표기만 다름)"
    assert ev.judge(src, None)[0] == "미연결"
    assert ev.judge(src, {**r("1", "락티스 (100B)"), "company_matched": False})[0] == "미연결"


def test_human_review_survives_rerun_and_flags_changes(tmp_path):
    import csv
    p = tmp_path / "review.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ev.REVIEW_COLS)
        w.writeheader()
        w.writerow({"입력 상품명": "A 상품", "검토 당시 연결 신고번호": "1", "판정(사람 검토)": "정답",
                    "검토 메모": "포장 확인", "근거": "신고번호 사진", "검토일": "2026-10-28", "검토자": "Ason"})
    before = p.read_bytes()
    rv = ev.load_review(p)
    same = ev.merge_review({"입력 상품명": "A 상품", "연결 신고번호": "1"}, rv)
    moved = ev.merge_review({"입력 상품명": "A 상품", "연결 신고번호": "2"}, rv)
    new = ev.merge_review({"입력 상품명": "B 상품", "연결 신고번호": "3"}, rv)
    assert same["판정(사람 검토)"] == "정답" and same["근거"] == "신고번호 사진" and not same["재검토 필요"]
    assert moved["재검토 필요"].startswith("예")            # 연결이 바뀌면 이전 판정을 그대로 믿지 않음
    assert new["판정(사람 검토)"] == "" and p.read_bytes() == before   # 검토 파일은 읽기만 함
