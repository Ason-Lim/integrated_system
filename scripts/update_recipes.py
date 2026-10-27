#!/usr/bin/env python3
"""공공 레시피 DB를 내려받아 로컬 레시피 카탈로그(JSON)로 저장한다 (표준 라이브러리만 사용).

출처
  1) 식품안전나라 조리식품 레시피 DB (COOKRCP01) — 재료·조리순서·사진·영양
  2) 농식품정보누리 레시피 (기본정보 / 재료정보 / 과정정보 Grid)

출력: var/recipes/recipes.json   (서버는 이 파일만 읽는다. API 호출은 이 스크립트에서만)
실행: venv/bin/python scripts/update_recipes.py [--limit N] [--only fs|epis]
"""
from __future__ import annotations

import argparse, json, os, re, sys, tempfile, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("RECIPE_CATALOG_PATH", ROOT / "var" / "recipes" / "recipes.json"))
PAGE = 1000  # 두 API 모두 1회 최대 1000건

EPIS_GRIDS = {
    "basic": "Grid_20150827000000000226_1",
    "ingredient": "Grid_20150827000000000227_1",
    "process": "Grid_20150827000000000228_1",
}


def load_env() -> dict:
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    env.update({k: v for k, v in os.environ.items() if k in env})
    return env


def fetch_json(url: str, tries: int = 3) -> dict:
    last = None
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (n + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def _rows(data: dict) -> tuple[list[dict], int | None]:
    root = next(iter(data.values())) if isinstance(data, dict) and data else {}
    if not isinstance(root, dict):
        return [], None
    total = root.get("total_count") or root.get("totalCnt")
    try:
        total = int(total) if total is not None else None
    except ValueError:
        total = None
    return root.get("row") or [], total


# ── 재료 문자열 파싱 ───────────────────────────────────────────
_SECTION = re.compile(r"^\s*[\[●•■◆○◎·\-]*\s*([^:：\]]{1,12})\s*[\]:：]\s*")
_AMOUNT = re.compile(r"^(?P<name>[^\d½⅓¼¾(（]+?)\s*(?P<amount>[\d½⅓¼¾].*|\(.*|약.*|조금.*|적당.*|약간.*)?$")


def _split_top(s: str) -> list[str]:
    """괄호 안 쉼표는 무시하고 쉼표/줄바꿈으로 나눈다."""
    out, buf, depth = [], [], 0
    for ch in s:
        if ch in "([（":
            depth += 1
        elif ch in ")]）" and depth:
            depth -= 1
        if ch in ",\n" and depth == 0:
            out.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


_GROUP_WORD = re.compile(r"(양념장?|소스|드레싱|재료|육수|고명|반죽|토핑|소금물|양념물|국물|장식|곁들임)$")


def normalize_name(name: str) -> str:
    """'[절임용 소금물] 소금' → '소금', '허브오일드레싱 저염소금' → '저염소금'"""
    n = re.sub(r"^\s*[\[(（<][^\])）>]*[\])）>]\s*", "", name or "").strip()
    n = re.split(r"\s*[>:：]\s*", n)[-1].strip()   # '초코크림 > 아몬드가루', '발사믹소스:간장
    parts = n.split(" ")
    cut = max((i for i, t in enumerate(parts[:-1]) if _GROUP_WORD.search(t)), default=-1)
    parts = parts[cut + 1:]
    return " ".join(parts).strip(" .·-")


def parse_ingredients(raw: str, title: str = "") -> list[dict]:
    items, seen = [], set()
    lines = [l for l in (raw or "").split("\n") if l.strip()]
    # 첫 줄이 쉼표·숫자 없는 한 단어(예: "된장국")면 요리 이름 머리말이므로 버린다
    if len(lines) > 1 and not re.search(r"[,\d]", lines[0]):
        lines = lines[1:]
    for tok in _split_top("\n".join(lines)):
        tok = _SECTION.sub("", tok).strip(" ·-●•■")
        if not tok or tok == title:
            continue
        m = _AMOUNT.match(tok)
        if not m:
            continue
        name = normalize_name(re.sub(r"\s+", " ", m.group("name")))
        amount = (m.group("amount") or "").strip()
        # 섹션 제목(재료, 양념 등)·문장형 토큰은 제외
        if not name or len(name) > 15 or name in {"재료", "주재료", "부재료", "양념", "양념장", "소스", "고명"}:
            continue
        if not amount and " " in name and len(name) > 8:
            continue
        if name in seen:
            continue
        seen.add(name)
        items.append({"name": name, "amount": amount})
    return items


def clean_step(text: str) -> str:
    """'1. 토마토를 데친다.a' → '토마토를 데친다.' (원문 번호·끝 알파벳 표식 제거)"""
    txt = re.sub(r"\s+", " ", text or "").strip()          # 원문 줄바꿈은 한 문장으로 잇는다
    txt = re.sub(r"\s*[a-z]$", "", txt).strip()
    return re.sub(r"^\d+\s*[.)]\s*", "", txt)


# ── 식품안전나라 COOKRCP01 ────────────────────────────────────
def collect_foodsafety(env: dict, limit: int | None) -> list[dict]:
    key = env.get("FOODSAFETY_API_KEY")
    svc = env.get("FOODSAFETY_RECIPE_SERVICE_ID") or "COOKRCP01"
    if not key:
        print("  ! FOODSAFETY_API_KEY 없음 — 건너뜀")
        return []
    out, start, total = [], 1, None
    while True:
        end = start + PAGE - 1
        rows, t = _rows(fetch_json(f"http://openapi.foodsafetykorea.go.kr/api/{key}/{svc}/json/{start}/{end}"))
        total = total or t
        for r in rows:
            name = (r.get("RCP_NM") or "").strip()
            if not name:
                continue
            steps = []
            for i in range(1, 21):
                txt = clean_step(r.get(f"MANUAL{i:02d}") or "")
                if txt:
                    steps.append({"text": txt, "image": (r.get(f"MANUAL_IMG{i:02d}") or "").strip() or None})
            out.append({
                "id": f"fs-{r.get('RCP_SEQ')}",
                "source": "foodsafety",
                "source_name": "식품안전나라 조리식품 레시피 DB",
                "name": name,
                "summary": (r.get("RCP_NA_TIP") or "").strip(),
                "category": (r.get("RCP_PAT2") or "").strip(),
                "method": (r.get("RCP_WAY2") or "").strip(),
                "servings": None,
                "time": None,
                "kcal": (r.get("INFO_ENG") or "").strip() or None,
                "tags": [t for t in re.split(r"[,#\s]+", r.get("HASH_TAG") or "") if t],
                "image": (r.get("ATT_FILE_NO_MAIN") or "").strip() or None,
                "ingredients_raw": (r.get("RCP_PARTS_DTLS") or "").strip(),
                "ingredients": parse_ingredients(r.get("RCP_PARTS_DTLS") or "", name),
                "steps": steps,
            })
        print(f"  식품안전나라 {start}~{end}: {len(rows)}건 (누적 {len(out)} / 전체 {total})")
        if not rows or (total and end >= total) or (limit and len(out) >= limit):
            break
        start = end + 1
    return out[:limit] if limit else out


# ── 농식품정보누리 레시피 ─────────────────────────────────────
def _epis_all(base: str, key: str, grid: str, limit: int | None = None) -> list[dict]:
    out, start = [], 1
    while True:
        end = start + PAGE - 1
        rows, total = _rows(fetch_json(f"{base}/{key}/json/{grid}/{start}/{end}"))
        out += rows
        if not rows or (total and end >= total) or (limit and len(out) >= limit):
            return out
        start = end + 1


def collect_epis(env: dict, limit: int | None) -> list[dict]:
    key, base = env.get("EPIS_RECIPE_API_KEY"), (env.get("EPIS_RECIPE_API_BASE_URL") or "").rstrip("/")
    if not key or not base:
        print("  ! EPIS_RECIPE_API_KEY / BASE_URL 없음 — 건너뜀")
        return []
    basic = _epis_all(base, key, EPIS_GRIDS["basic"], limit)
    print(f"  농식품정보누리 기본정보: {len(basic)}건")
    ing, proc = defaultdict(list), defaultdict(list)
    try:
        rows = _epis_all(base, key, EPIS_GRIDS["ingredient"])
        for r in sorted(rows, key=lambda r: int(r.get("IRDNT_SN") or 0)):
            ing[str(r.get("RECIPE_ID"))].append(r)
        print(f"  농식품정보누리 재료정보: {len(rows)}건")
    except Exception as e:  # noqa: BLE001
        print(f"  ! 재료정보 실패: {e}")
    try:
        rows = _epis_all(base, key, EPIS_GRIDS["process"])
        for r in sorted(rows, key=lambda r: int(r.get("COOKING_NO") or 0)):
            proc[str(r.get("RECIPE_ID"))].append(r)
        print(f"  농식품정보누리 과정정보: {len(rows)}건")
    except Exception as e:  # noqa: BLE001
        print(f"  ! 과정정보 실패: {e}")

    out = []
    for b in basic[:limit] if limit else basic:
        rid, name = str(b.get("RECIPE_ID")), (b.get("RECIPE_NM_KO") or "").strip()
        if not name:
            continue
        ings = []
        for r in ing.get(rid, []):
            n = normalize_name((r.get("IRDNT_NM") or "").strip())
            if n and n not in {x["name"] for x in ings}:
                ings.append({"name": n, "amount": (r.get("IRDNT_CPCTY") or "").strip(),
                             "kind": (r.get("IRDNT_TY_NM") or "").strip() or None})
        out.append({
            "id": f"epis-{rid}",
            "source": "epis",
            "source_name": "농식품정보누리 레시피",
            "name": name,
            "summary": (b.get("SUMRY") or "").strip(),
            "category": " · ".join(x for x in [(b.get("NATION_NM") or "").strip(), (b.get("TY_NM") or "").strip()] if x),
            "method": "",
            "servings": (b.get("QNT") or "").strip() or None,
            "time": (b.get("COOKING_TIME") or "").strip() or None,
            "kcal": (b.get("CALORIE") or "").strip() or None,
            "level": (b.get("LEVEL_NM") or "").strip() or None,
            "tags": [],
            "image": None,
            "ingredients_raw": ", ".join(f"{x['name']} {x['amount']}".strip() for x in ings),
            "ingredients": ings,
            "steps": [{"text": (r.get("COOKING_DC") or "").strip(),
                       "image": (r.get("STRE_STEP_IMAGE_URL") or "").strip() or None}
                      for r in proc.get(rid, []) if (r.get("COOKING_DC") or "").strip()],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="출처별 최대 건수 (시험용)")
    ap.add_argument("--only", choices=["fs", "epis"])
    a = ap.parse_args()
    env = load_env()
    print(f"[{datetime.now():%F %T}] 레시피 수집 시작")
    recipes, counts, errors = [], {}, {}
    for code, fn in (("fs", collect_foodsafety), ("epis", collect_epis)):
        if a.only and a.only != code:
            continue
        try:
            got = fn(env, a.limit)
            recipes += got
            counts[code] = len(got)
        except Exception as e:  # noqa: BLE001
            errors[code] = str(e)
            print(f"  ! {code} 수집 실패: {e}")
    if not recipes:
        print("수집된 레시피가 없어 기존 파일을 유지합니다.")
        return 1
    # 이전 파일에서 실패한 출처는 유지 (한쪽 API 장애로 데이터가 줄지 않게)
    if errors and OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8")).get("recipes", [])
            keep = [r for r in prev if r.get("source") in {"foodsafety" if c == "fs" else "epis" for c in errors}]
            recipes += keep
            print(f"  실패한 출처는 이전 데이터 {len(keep)}건 유지")
        except Exception:  # noqa: BLE001
            pass
    with_steps = sum(1 for r in recipes if r["steps"])
    doc = {"generated_at": datetime.now().isoformat(timespec="seconds"), "counts": counts,
           "errors": errors, "total": len(recipes), "recipes": recipes}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=OUT.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, OUT)
    print(f"[{datetime.now():%F %T}] 저장: {OUT} (총 {len(recipes)}건, 조리순서 있음 {with_steps}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
