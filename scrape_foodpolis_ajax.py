import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import json
import datetime

load_dotenv()
USER_ID = os.getenv("FOODPOLIS_ID")
USER_PW = os.getenv("FOODPOLIS_PW")

TODAY = datetime.datetime.now().strftime("%Y-%m-%d")
# 저장 경로: integrated_system/var/foodpolis/foodpolis_rank_YYYY-MM-DD.json
# ※ ui_ux/src/data/trend_examples_*.json 은 홈 화면 예시 질문 파일(launchd가 매일 10:00 생성)이므로 여기에 쓰지 않는다.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.environ.get("FOODPOLIS_OUTPUT_DIR", os.path.join(BASE_DIR, "var", "foodpolis"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"foodpolis_rank_{TODAY}.json")
if "trend_examples_" in os.path.basename(OUTPUT_FILE) or os.path.join("ui_ux", "src", "data") in OUTPUT_FILE:
    raise SystemExit("Foodpolis 결과는 ui_ux/src/data 에 저장할 수 없습니다 (홈 화면 예시 파일 보호).")

LOGIN_URL = "https://www.foodpolis.kr/dfip/fo/cms/mal/login/form.do"
RANKING_URL = "https://www.foodpolis.kr/food24/fo/poc/main/pocMain.do"

with sync_playwright() as p:
    print("1. 브라우저 실행 및 로그인...")
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    # 로그인
    page.goto(LOGIN_URL, wait_until="networkidle")
    page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const btn of btns) { if (btn.innerText.trim() === '아이디') { btn.click(); return; } }
    }""")
    page.wait_for_timeout(1000)
    page.fill("input[name='userId']", USER_ID)
    page.fill("input[name='userPassword']", USER_PW)
    page.evaluate("""() => {
        const btn = document.getElementById('iLogin');
        if (btn) { const ev = new MouseEvent('click', {bubbles:true, cancelable:true, view:window}); btn.dispatchEvent(ev); }
    }""")
    
    try:
        page.wait_for_function("() => !window.location.href.includes('/login/')", timeout=15000)
        print("   ✅ 로그인 성공!")
    except:
        print("   ❌ 로그인 실패")
        browser.close()
        exit(1)

    # 랭킹 페이지 이동
    print("2. 랭킹 페이지 이동 및 실제 카테고리 조회...")
    page.goto(RANKING_URL, wait_until="networkidle")
    page.wait_for_timeout(3000)

    # 실제 서버의 2단계 카테고리 목록 가져오기
    class2_res = page.evaluate("""
        async () => {
            const res = await fetch('/food24/fo/poc/main/SellRankingClass2NmList.ajax', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-XSRF-TOKEN': document.cookie.match(/XSRF-TOKEN=([^;]+)/)?.[1] || ''},
                body: JSON.stringify({ gnspsGubun: '1', chn: '편의점' })
            });
            return await res.json();
        }
    """)
    
    # 카테고리 이름 추출
    categories_from_server = []
    if isinstance(class2_res, list):
        categories_from_server = [str(x) for x in class2_res]
    elif isinstance(class2_res, dict):
        for val in class2_res.values():
            if isinstance(val, list):
                categories_from_server = [str(x) for x in val]
                break
    
    print(f"   -> 서버 카테고리 목록 (앞 10개): {categories_from_server[:10]}")

    # 🎯 UI 카테고리와 매칭할 검색 키워드 정의
    ui_mapping = [
        {"category": "선물용", "icon": "Gift", "keywords": ["세트", "선물", "가공"]},
        {"category": "간식/디저트", "icon": "Cookie", "keywords": ["과자", "디저트", "빵", "초콜릿", "아이스크림"]},
        {"category": "레시피/요리", "icon": "Utensils", "keywords": ["면", "소스", "요리", "반찬", "국", "식재료"]},
        {"category": "제철과일", "icon": "Leaf", "keywords": ["과일", "과채"]},
    ]
    
    final_json = []
    print("3. 실제 카테고리별 데이터 수집...")

    for ui_cat in ui_mapping:
        # 서버 카테고리 목록에서 해당 키워드가 포함된 카테고리 찾기
        matched_category = None
        for keyword in ui_cat["keywords"]:
            for server_cat in categories_from_server:
                if keyword in server_cat:
                    matched_category = server_cat
                    break
            if matched_category:
                break
        
        # 매칭되는 카테고리가 없으면, 기본값(서버 카테고리 중 첫 번째) 사용
        if not matched_category:
            matched_category = categories_from_server[0] if categories_from_server else "기타"
            print(f"   ⚠️ '{ui_cat['category']}'에 맞는 카테고리가 없어 '{matched_category}'로 대체합니다.")

        class2_name = matched_category
        
        # 3단계 카테고리(class3Nm) 조회
        class3_res = page.evaluate(f"""
            async () => {{
                const res = await fetch('/food24/fo/poc/main/SellRankingClass3NmList.ajax', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-XSRF-TOKEN': document.cookie.match(/XSRF-TOKEN=([^;]+)/)?.[1] || ''}},
                    body: JSON.stringify({{ gnspsGubun: '1', class2Nm: '{class2_name}', chn: '편의점' }})
                }});
                return await res.json();
            }}
        """)
        
        class3_name = class2_name # 기본값
        if isinstance(class3_res, list) and len(class3_res) > 0:
            class3_name = str(class3_res[0])
        elif isinstance(class3_res, dict):
            for val in class3_res.values():
                if isinstance(val, list) and len(val) > 0:
                    class3_name = str(val[0])
                    break

        # 판매 순위(sellRnk) 조회
        rank_res = page.evaluate(f"""
            async () => {{
                const res = await fetch('/food24/fo/poc/main/sellRnk.ajax', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-XSRF-TOKEN': document.cookie.match(/XSRF-TOKEN=([^;]+)/)?.[1] || ''}},
                    body: JSON.stringify({{ gnspsGubun: '1', chn: '편의점', class2Nm: '{class2_name}', class3Nm: '{class3_name}' }})
                }});
                return await res.json();
            }}
        """)

        # 상품명(prodNm) 추출
        keyword = class3_name
        if isinstance(rank_res, list) and len(rank_res) > 0 and isinstance(rank_res[0], dict):
            keyword = rank_res[0].get('prodNm') or class3_name
        elif isinstance(rank_res, dict):
            if isinstance(rank_res.get('data'), list) and len(rank_res['data']) > 0 and isinstance(rank_res['data'][0], dict):
                keyword = rank_res['data'][0].get('prodNm') or class3_name
            else:
                for val in rank_res.values():
                    if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                        keyword = val[0].get('prodNm') or class3_name
                        break
        
        print(f"   [{ui_cat['category']}] {class2_name} > {class3_name} => {keyword}")
        
        final_json.append({
            "category": ui_cat["category"],
            "icon": ui_cat["icon"],
            "keyword": keyword,
            "question": f"{keyword} 중에 인기 있는 걸로 추천해줘"
        })

    # 4. JSON 저장
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)
        
    print(f"🎉 저장 완료: {OUTPUT_FILE}")
    print(json.dumps(final_json, ensure_ascii=False, indent=2))

    browser.close()