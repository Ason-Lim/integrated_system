#!/bin/bash
# Foodpolis 크롤링 자동 실행 스크립트

# 프로젝트 폴더로 이동 (load_dotenv가 .env를 찾을 수 있도록)
cd /Users/mom/integrated_system

# 가상환경 활성화
source venv/bin/activate

# 파이썬 스크립트 실행 및 로그 저장
echo "=== [$(date)] Foodpolis 크롤링 시작 ===" >> /Users/mom/integrated_system/var/foodpolis_scrape.log
python scrape_foodpolis_full.py >> /Users/mom/integrated_system/var/foodpolis_scrape.log 2>&1
echo "=== [$(date)] 크롤링 종료 (종료 코드: $?) ===" >> /Users/mom/integrated_system/var/foodpolis_scrape.log
