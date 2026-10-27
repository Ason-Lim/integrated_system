import os
import json
import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
USER_ID = os.getenv("FOODPOLIS_ID")
USER_PW = os.getenv("FOODPOLIS_PW")

# 저장 디렉토리 설정
BASE_DIR = "/Users/mom/integrated_system/data/foodpolis_raw"
TODAY = datetime.datetime.now().strftime("%Y-%m-%d")
OUTPUT_DIR = os.path.join(BASE_DIR, TODAY)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 로그인 및 랭킹 페이지 URL
LOGIN_URL = "https://www.foodpolis.kr/dfip/fo/cms/mal/login/form.do"
RANKING_URL = "https://www.foodpolis.kr/food24/fo/poc/main/pocMain.do"

# 수집할 채널 목록 (사이트에서 확인된 채널 + 추정)
CHANNELS = ["편의점", "슈퍼마켓", "외식", "온라인"]

# 상품 구분 (1: 가공식품, 2: 신선식품 등 - 사이트 구조에 따라 추가)
GNSPS_GUBUNS = ["1", "2"]

def login(page):
    """Foodpolis 로그인"""
    page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
    
    # '아이디' 탭 클릭
    page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const btn of btns) { if (btn.innerText.trim() === '아이디') { btn.click(); return; } }
    }""")
    page.wait_for_timeout(1000)
    
    # ID/PW 입력
    page.fill("input[name='userId']", USER_ID)
    page.fill("input[name='userPassword']", USER_PW)
    
    # 로그인 버튼 클릭 (이벤트 디스패치로 iframe 간섭 우회)
    page.evaluate("""() => {
        const btn = document.getElementById('iLogin');
        if (btn) { const ev = new MouseEvent('click', {bubbles:true, cancelable:true, view:window}); btn.dispatchEvent(ev); }
    }""")
    
    # 로그인 성공 대기
    try:
        page.wait_for_function("() => !window.location.href.includes('/login/')", timeout=15000)
        print("   ✅ 로그인 성공!")
    except:
        print("   ❌ 로그인 실패")
        raise Exception("로그인 실패")

def fetch_categories(page, gubun, channel):
    """2단계 카테고리 목록 조회"""
    result = page.evaluate(f"""
        async () => {{
            const res = await fetch('/food24/fo/poc/main/SellRankingClass2NmList.ajax', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-XSRF-TOKEN': document.cookie.match(/XSRF-TOKEN=([^;]+)/)?.[1] || ''}},
                body: JSON.stringify({{ gnspsGubun: '{gubun}', chn: '{channel}' }})
            }});
            return await res.json();
        }}
    """)
    # 리스트 또는 딕셔너리에서 카테고리 이름 추출
    if isinstance(result, list):
        return [str(x) for x in result]
    elif isinstance(result, dict):
        for val in result.values():
            if isinstance(val, list):
                return [str(x) for x in val]
    return []

def fetch_sub_categories(page, gubun, channel, class2_nm):
    """3단계 카테고리 목록 조회"""
    result = page.evaluate(f"""
        async () => {{
            const res = await fetch('/food24/fo/poc/main/SellRankingClass3NmList.ajax', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-XSRF-TOKEN': document.cookie.match(/XSRF-TOKEN=([^;]+)/)?.[1] || ''}},
                body: JSON.stringify({{ gnspsGubun: '{gubun}', class2Nm: '{class2_nm}', chn: '{channel}' }})
            }});
            return await res.json();
        }}
    """)
    if isinstance(result, list):
        return [str(x) for x in result]
    elif isinstance(result, dict):
        for val in result.values():
            if isinstance(val, list):
                return [str(x) for x in val]
    return []

def fetch_rankings(page, gubun, channel, class2_nm, class3_nm):
    """판매 순위 데이터 조회"""
    result = page.evaluate(f"""
        async () => {{
            const res = await fetch('/food24/fo/poc/main/sellRnk.ajax', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-XSRF-TOKEN': document.cookie.match(/XSRF-TOKEN=([^;]+)/)?.[1] || ''}},
                body: JSON.stringify({{ gnspsGubun: '{gubun}', chn: '{channel}', class2Nm: '{class2_nm}', class3Nm: '{class3_nm}' }})
            }});
            return await res.json();
        }}
    """)
    return result

with sync_playwright() as p:
    print("1. 브라우저 실행 및 로그인...")
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    login(page)
    
    print("2. 랭킹 페이지 이동...")
    page.goto(RANKING_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(3000)
    
    # 수집 결과 저장 변수
    all_categories = {}
    all_rankings = []
    
    total_channels = len(CHANNELS) * len(GNSPS_GUBUNS)
    current = 0
    
    for gubun in GNSPS_GUBUNS:
        for channel in CHANNELS:
            current += 1
            print(f"\n[{current}/{total_channels}] 수집 중: gubun={gubun}, channel={channel}")
            
            # 2단계 카테고리 목록
            class2_list = fetch_categories(page, gubun, channel)
            if not class2_list:
                print(f"   ⚠️ 카테고리 없음 (건너뜀)")
                continue
            
            all_categories[f"{gubun}_{channel}"] = class2_list
            print(f"   - 2단계 카테고리 {len(class2_list)}개: {class2_list[:5]}...")
            
            for class2_nm in class2_list:
                # 3단계 카테고리 목록
                class3_list = fetch_sub_categories(page, gubun, channel, class2_nm)
                if not class3_list:
                    class3_list = [class2_nm]  # 3단계가 없으면 2단계를 그대로 사용
                
                for class3_nm in class3_list:
                    # 판매 순위 데이터
                    rank_data = fetch_rankings(page, gubun, channel, class2_nm, class3_nm)
                    
                    # 데이터 저장
                    entry = {
                        "gnspsGubun": gubun,
                        "channel": channel,
                        "class2Nm": class2_nm,
                        "class3Nm": class3_nm,
                        "rankings": rank_data
                    }
                    all_rankings.append(entry)
                    
                    # 진행 상황 출력 (데이터가 있는 경우만)
                    if rank_data and (isinstance(rank_data, list) and len(rank_data) > 0):
                        sample = rank_data[0].get('prodNm', 'N/A') if isinstance(rank_data[0], dict) else str(rank_data[0])
                        print(f"      └ {class3_nm}: {len(rank_data)}건 (예: {sample})")
    
    # 3. JSON 저장
    print("\n4. 데이터 저장 중...")
    
    # 카테고리 구조 저장
    with open(os.path.join(OUTPUT_DIR, "categories.json"), "w", encoding="utf-8") as f:
        json.dump(all_categories, f, ensure_ascii=False, indent=2)
    
    # 전체 랭킹 데이터 저장
    with open(os.path.join(OUTPUT_DIR, "rankings_all.json"), "w", encoding="utf-8") as f:
        json.dump(all_rankings, f, ensure_ascii=False, indent=2)
    
    # 수집 요약 저장
    summary = {
        "collected_at": datetime.datetime.now().isoformat(),
        "total_entries": len(all_rankings),
        "channels": CHANNELS,
        "gubuns": GNSPS_GUBUNS,
        "output_dir": OUTPUT_DIR
    }
    with open(os.path.join(OUTPUT_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n🎉 저장 완료: {OUTPUT_DIR}")
    print(f"   - categories.json: {len(all_categories)}개 카테고리 그룹")
    print(f"   - rankings_all.json: {len(all_rankings)}개 랭킹 항목")
    print(f"   - summary.json: 수집 요약")
    
    browser.close()
