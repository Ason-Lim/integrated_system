#!/usr/bin/env python3
"""농촌진흥청 농사로 '이달의 식재료' Open API → 식재료 보관·손질·구입요령 카탈로그 (표준 라이브러리만 사용).

키:  .env 의 NONGSARO_API_KEY  (농사로 > 공공데이터 개방 > OpenAPI 신청 후 발급)
출력: var/knowledge/storage_guides.json   (서버는 이 파일만 읽는다)
실행: venv/bin/python scripts/update_storage_guides.py            전체 수집
      venv/bin/python scripts/update_storage_guides.py --probe    응답 구조만 확인 (키는 출력하지 않음)
      venv/bin/python scripts/update_storage_guides.py --years 2016-2019 수집 연도 지정
"""
from __future__ import annotations

import argparse, html, json, os, re, sys, tempfile, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("STORAGE_GUIDE_PATH", ROOT / "var" / "knowledge" / "storage_guides.json"))
BASE = os.environ.get("NONGSARO_API_BASE", "http://api.nongsaro.go.kr/service/monthFd")
DETAIL_PAGE = "https://www.nongsaro.go.kr/portal/ps/psr/psrb/monthFdmtDtl.ps?cntntsNo={}"
SOURCE_NAME = "농촌진흥청 농사로 '이달의 식재료'"

# 본문 '■ 보관법' 같은 머리말 → 저장 키
SECTIONS = {
    "purchase": r"구입\s*요령|고르는\s*(?:법|방법|요령)|선택\s*요령",
    "storage": r"보관\s*(?:법|방법|요령)",
    "prep": r"손질\s*(?:법|방법|요령)|세척\s*(?:법|방법)",
    "eat": r"섭취\s*(?:법|방법)|먹는\s*(?:법|방법)",
}
# 머리말이 없을 때 태그 이름으로 추정
# 실제 필드(농사로 샘플코드 기준): prchCheatDtl 구입요령, cstdyMthDtl 보관방법, ntkMthDtl 섭취방법
TAG_HINTS = {"purchase": ("prch", "purchs"), "storage": ("cstdy", "strg", "stor"),
             "prep": ("trmng", "prpr", "clean"), "eat": ("ntk",)}
# 12개월이 다 찬 해는 2016~2019 (2015·2020·2023 일부, 2021~ 대부분 없음). 겹치는 항목은 이름으로 합친다.
DEFAULT_YEARS = list(range(2015, 2024))
ANY_HEAD = re.compile(r"[■□●◆▶]\s*([^\n■□●◆▶\-]{1,15})")


def load_env() -> dict:
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    for k in ("NONGSARO_API_KEY", "NONGSARO_API_BASE"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def call(op: str, key: str, **params) -> ET.Element:
    q = urllib.parse.urlencode({"apiKey": key, **params})
    last = None
    for n in range(3):
        try:
            with urllib.request.urlopen(f"{BASE}/{op}?{q}", timeout=30) as r:
                return ET.fromstring(r.read())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (n + 1))
    raise RuntimeError(f"{op}: {type(last).__name__}: {last}")


def items(root: ET.Element) -> list[dict]:
    out = []
    for it in root.iter("item"):
        out.append({c.tag: (c.text or "").strip() for c in it})
    return out


def header(root: ET.Element) -> tuple[str, str]:
    return (root.findtext(".//resultCode") or "").strip(), (root.findtext(".//resultMsg") or "").strip()


def clean_text(s: str) -> str:
    s = html.unescape(s if isinstance(s, str) else "")
    s = re.sub(r"<\s*br\s*/?>|</p>|</li>|</div>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("\r", "")
    s = re.sub(r"[ \t ]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def bullets(block: str) -> list[str]:
    out = []
    for line in block.split("\n"):
        line = re.sub(r"^\s*[-·•○◦※▪]\s*", "", line).strip()
        # 화면 탭 이름만 있는 줄('보관법 손질법')은 버린다
        if re.fullmatch(r"(?:[가-힣]{1,6}(?:법|요령|특성|성분|효능|정보)\s*)+", line):
            continue
        if line and not re.fullmatch(r"[■□●◆▶].*", line):
            out.append(line)
    return out[:12]


def split_sections(text: str) -> dict[str, list[str]]:
    """'■ 보관법 - ... ■ 손질법 - ...' 본문을 구입요령·보관법·손질법으로 나눈다."""
    text = clean_text(text)
    heads = list(ANY_HEAD.finditer(text))
    out: dict[str, list[str]] = {}
    for i, m in enumerate(heads):
        title = m.group(1).strip()
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        for key, pat in SECTIONS.items():
            if re.fullmatch(rf"\s*(?:{pat})\s*", title) and key not in out:
                b = bullets(body)
                if b:
                    out[key] = b
    return out


def parse_detail(fields: dict) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    for tag, val in fields.items():          # 1) 본문 안의 ■ 머리말 (예: 보관방법 필드 안의 '■ 손질법')
        for k, v in split_sections(val).items():
            sections.setdefault(k, v)
    for k, hints in TAG_HINTS.items():        # 2) 필드 이름이 곧 항목인 경우 (머리말 없는 본문)
        if k in sections:
            continue
        for tag, val in fields.items():
            if any(h in tag.lower() for h in hints) and clean_text(val) and not ANY_HEAD.search(clean_text(val)):
                sections[k] = bullets(clean_text(val)) or [clean_text(val)]
                break
    return sections


def aliases(name: str) -> list[str]:
    parts = re.split(r"[()（）\[\],·/]", name)
    return [p.strip() for p in parts if p.strip() and p.strip() != name]


def _name_of(row: dict) -> str:
    for k in ("fdmtNm", "cntntsSj", "fdNm", "sj"):
        if row.get(k):
            return row[k]
    return next((v for k, v in row.items() if k.lower().endswith("nm") and v), "")


def probe(key: str) -> None:
    today = date.today()
    yl = call("monthFdYearLst", key, thisYear=today.year, thisMonth=f"{today.month:02d}")
    print("조회 가능 연도:", [it.get("year") for it in items(yl)])
    root = call("monthFdmtLst", key, thisYear=2019, thisMonth="10")   # 데이터가 온전한 해로 점검
    print("목록 resultCode/Msg:", header(root))
    rows = items(root)
    print("목록 건수:", len(rows), "| 필드:", list(rows[0].keys()) if rows else [])
    if rows:
        print("첫 행:", {k: v[:40] for k, v in rows[0].items()})
        d = call("monthFdmtDtl", key, cntntsNo=rows[0].get("cntntsNo", ""))
        print("상세 resultCode/Msg:", header(d))
        drows = items(d)
        if drows:
            print("상세 필드:", {k: len(v) for k, v in drows[0].items()})
            print("추출 결과:", json.dumps(parse_detail(drows[0]), ensure_ascii=False)[:800])
        else:
            print("상세 응답 앞부분:", ET.tostring(d, encoding="unicode")[:600])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--years", help="수집 연도 (예: 2016-2019 또는 2016,2018). 기본 2015-2023")
    a = ap.parse_args()
    env = load_env()
    global BASE
    BASE = env.get("NONGSARO_API_BASE", BASE)
    key = env.get("NONGSARO_API_KEY")
    if not key:
        print("NONGSARO_API_KEY 가 .env 에 없습니다. 농사로(nongsaro.go.kr) > 공공데이터 개방 > OpenAPI 신청 후 키를 넣어 주세요.")
        return 2
    if a.probe:
        probe(key)
        return 0

    years = DEFAULT_YEARS
    if a.years:
        if "-" in a.years:
            lo, hi = map(int, a.years.split("-"))
            years = list(range(lo, hi + 1))
        else:
            years = [int(y) for y in a.years.split(",")]
    print(f"[{datetime.now():%F %T}] 농사로 이달의 식재료 수집 시작 ({years[0]}~{years[-1]}년)")
    listing: dict[str, dict] = {}
    names: set[str] = set()
    for y in years:
        for m in range(1, 13):
            try:
                root = call("monthFdmtLst", key, thisYear=y, thisMonth=f"{m:02d}")
            except Exception as e:  # noqa: BLE001
                print(f"  ! {y}-{m:02d} 목록 실패: {e}")
                continue
            for row in items(root):
                no, nm = row.get("cntntsNo"), (row.get("fdmtNm") or "").strip()
                if no and no not in listing and nm not in names:   # 같은 식재료가 해마다 반복 → 이름으로도 중복 제거
                    listing[no] = {**row, "_month": m}
                    names.add(nm)
            time.sleep(0.1)
    print(f"  식재료 목록: {len(listing)}건")

    guides, failed = [], 0
    for no, row in listing.items():
        try:
            drows = items(call("monthFdmtDtl", key, cntntsNo=no))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ! 상세 실패 {no}: {e}")
            continue
        fields = {k: v for k, v in {**row, **(drows[0] if drows else {})}.items() if not k.startswith("_")}
        sec = parse_detail(fields)
        name = clean_text(_name_of(fields))
        if not name or not ({"storage", "prep", "eat"} & sec.keys()):
            continue
        guides.append({
            "id": f"nongsaro-{no}", "name": name, "aliases": aliases(name),
            "month": row.get("_month"),
            "purchase": sec.get("purchase", []), "storage": sec.get("storage", []), "prep": sec.get("prep", []),
            "eat": sec.get("eat", []),
            "source_name": SOURCE_NAME, "source_url": DETAIL_PAGE.format(no),
        })
        time.sleep(0.05)
    if not guides:
        print("보관법을 추출한 항목이 없어 기존 파일을 유지합니다. --probe 로 응답 구조를 확인해 주세요.")
        return 1
    doc = {"generated_at": datetime.now().isoformat(timespec="seconds"), "source": SOURCE_NAME,
           "total": len(guides), "failed": failed, "guides": guides}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=OUT.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, OUT)
    print(f"[{datetime.now():%F %T}] 저장: {OUT} (식재료 {len(guides)}건, 상세 실패 {failed}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
