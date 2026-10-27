"""농촌진흥청 농사로 Open API 공통 호출 (표준 라이브러리만 사용).

요청 형식: http://api.nongsaro.go.kr/service/{서비스}/{오퍼레이션}?apiKey=...  (XML 응답, UTF-8)
서비스·오퍼레이션·필드는 농사로 'OPEN API 목록'의 매뉴얼(apiManual/*.zip) 기준.
"""
from __future__ import annotations

import html, os, re, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://api.nongsaro.go.kr/service"
IMG_BASE = "https://www.nongsaro.go.kr/"


def api_key() -> str:
    key = os.environ.get("NONGSARO_API_KEY", "")
    p = ROOT / ".env"
    if not key and p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("NONGSARO_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
    return key


class NongsaroError(RuntimeError):
    pass


def call(service: str, op: str, key: str, **params) -> ET.Element:
    q = urllib.parse.urlencode({"apiKey": key, **{k: v for k, v in params.items() if v is not None}})
    last = None
    for n in range(3):
        try:
            with urllib.request.urlopen(f"{BASE}/{service}/{op}?{q}", timeout=30) as r:
                root = ET.fromstring(r.read())
            code = (root.findtext(".//resultCode") or "").strip()
            if code and code != "00":
                raise NongsaroError(f"{service}/{op} 결과코드 {code}: {(root.findtext('.//resultMsg') or '').strip()}")
            return root
        except NongsaroError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (n + 1))
    raise NongsaroError(f"{service}/{op}: {type(last).__name__}: {last}")


def items(root: ET.Element) -> list[dict]:
    return [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]


def first(root: ET.Element) -> dict:
    rows = items(root)
    return rows[0] if rows else {}


def paged(service: str, op: str, key: str, rows: int = 100, max_pages: int = 200, **params):
    """pageNo 를 올리며 모든 item 을 돌려준다 (totalCount 가 있으면 그만큼만)."""
    seen = 0
    for page in range(1, max_pages + 1):
        root = call(service, op, key, pageNo=page, numOfRows=rows, **params)
        got = items(root)
        yield from got
        seen += len(got)
        total = (root.findtext(".//totalCount") or "").strip()
        if not got or (total.isdigit() and seen >= int(total)) or len(got) < rows:
            return
        time.sleep(0.1)


def text(s: str | None) -> str:
    """HTML 본문 → 줄바꿈이 살아있는 평문"""
    s = html.unescape(s or "")
    s = re.sub(r"(?i)<\s*br\s*/?>|</p>|</li>|</div>|</tr>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s).replace("\r", "")
    s = re.sub(r"[ \t ]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def image_url(row: dict) -> str | None:
    if row.get("imgUrl"):
        return row["imgUrl"]
    cours = (row.get("rtnFileCours") or "").split("|")[0].strip()
    name = (row.get("rtnStreFileNm") or "").split("|")[0].strip()
    return f"{IMG_BASE}{cours.strip('/')}/{name}" if cours and name else None


def probe(service: str, op: str, key: str, **params) -> list[dict]:
    """응답 구조만 출력 (키는 출력하지 않음)"""
    root = call(service, op, key, **params)
    rows = items(root)
    print(f"  {service}/{op}: {len(rows)}건, totalCount={(root.findtext('.//totalCount') or '').strip() or '-'}")
    if rows:
        print("   필드:", {k: len(v) for k, v in rows[0].items()})
        print("   첫 행:", {k: v[:40] for k, v in list(rows[0].items())[:10]})
    return rows
