#!/usr/bin/env python3
"""B안: 키워드 하나로 네이버 블로그 쇼핑커넥트 글 초안 만들기.

내용은 우리 서비스의 공공 자료(농사로 보관·손질·고르는 법, 공공 레시피 DB, 지역특산물)만 쓰고 출처를 단다.
상품 링크는 넣지 않는다 — 스마트에디터의 '쇼핑커넥트' 기능으로 사람이 삽입한다 (대가성 배너 자동 생성).
가격은 쓰지 않는다 (수집 시점 가격이 바뀌므로 상품 카드가 보여주게 둔다).

출력: var/blog_drafts/YYYY-MM-DD_{키워드}.txt   (제목 / 태그 / 본문)
실행: venv/bin/python scripts/make_blog_draft.py 대봉감 --product "상품명(브랜드커넥트에서 고른 것)" [--product ...]
"""
from __future__ import annotations

import argparse, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shared import local_knowledge, recipe_catalog, storage_guides  # noqa: E402

DISCLOSURE = ("이 포스팅은 네이버 쇼핑 커넥트 활동의 일환으로, 판매 발생 시 일정액의 수수료를 제공받습니다. "
              "받은 수수료는 블로그와 무료 식품 추천 서비스 운영에 도움이 됩니다.")
LINK_SLOT = "▶ [여기에 스마트에디터 '쇼핑커넥트'로 상품 삽입: {name}]"


def ro(word: str) -> str:
    """받침 있으면 '으로'(ㄹ받침 제외), 없으면 '로' — '대봉감으로', '배로', '쌀로'"""
    ch = word[-1] if word else ""
    if "가" <= ch <= "힣":
        jong = (ord(ch) - 0xAC00) % 28
        return word + ("으로" if jong and jong != 8 else "로")
    return word + "로"


def build(keyword: str, products: list[str]) -> tuple[str, list[str], str]:
    title = f"[광고] {keyword} 고르는 법·보관법과 함께 보는 추천 상품"
    tags = [keyword, f"{keyword}보관법", f"{keyword}고르는법", "제철식재료", "쇼핑커넥트"]
    body: list[str] = [DISCLOSURE, ""]
    hit = storage_guides.find(keyword)
    if hit:
        g, asked = hit
        base = f" ('{g['name']}' 항목 기준)" if g["name"] != asked else ""
        body.append(f"■ {keyword} 고르는 법·보관법{base}")
        for key, label in (("purchase", "고르는 법"), ("storage", "보관법"), ("prep", "손질법"), ("eat", "먹는 법")):
            rows = g.get(key) or []
            if rows:
                body.append(f"[{label}]")
                body += [f"- {r}" for r in rows[:4]]
        body += [f"(출처: {g.get('source_name') or '농촌진흥청 농사로'})", ""]
    recipes = recipe_catalog.search(f"{keyword} 레시피", limit=2)
    if not recipes and hit:
        recipes = recipe_catalog.by_ingredient([hit[0]["name"]], limit=2)
    if recipes:
        body.append(f"■ {ro(keyword)} 만들어 보기")
        for r in recipes:
            ings = ", ".join(f"{i['name']} {i.get('amount') or ''}".strip() for i in r.get("ingredients", [])[:8])
            body.append(f"[{r['name']}] 재료: {ings}")
            body += [f"{n}. {st['text']}" for n, st in enumerate(r.get("steps", [])[:5], 1)]
            body.append(f"(출처: {r.get('source_name') or '공공 레시피 DB'})")
            body.append("")
    sp = local_knowledge.specialty_for(keyword)
    if sp:
        body += [f"■ 참고: {sp['name']}은(는) 농촌진흥청 농사로 지역특산물에 등록된 {sp['region']} 특산물입니다.", ""]
    body.append("■ 추천 상품")
    if products:
        body += [LINK_SLOT.format(name=p) for p in products]
    else:
        body.append(LINK_SLOT.format(name=f"브랜드커넥트에서 '{keyword}' 검색 후 선택"))
    body += ["", "※ 가격·배송·후기는 상품 페이지에서 최종 확인해 주세요."]
    return title, tags, "\n".join(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword")
    ap.add_argument("--product", action="append", default=[])
    a = ap.parse_args()
    title, tags, body = build(a.keyword, a.product)
    out_dir = ROOT / "var" / "blog_drafts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{date.today().isoformat()}_{a.keyword}.txt"
    out.write_text(f"제목: {title}\n태그: {', '.join(tags)}\n\n{body}\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
