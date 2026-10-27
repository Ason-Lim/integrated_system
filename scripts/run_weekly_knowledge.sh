#!/bin/bash
# 매주 월요일 10:20 launchd 실행: 공공 레시피 DB(+농사로 향토·종가음식) + 농사로 보관법 + 지역특산물·농가맛집
# (두 스크립트 모두 표준 라이브러리만 쓰므로 시스템 파이썬으로 실행)
cd "$(dirname "$0")/.." || exit 1
mkdir -p var/logs
LOG="var/logs/weekly_knowledge_$(date +%Y%m%d).log"
PY=/usr/bin/python3
[ -x "$PY" ] || PY="$(command -v python3)"
{
  echo "== $(date '+%F %T') 레시피 수집 ($PY)"; "$PY" scripts/update_recipes.py; echo "== 레시피 exit=$?"
  echo "== $(date '+%F %T') 보관법 수집"; "$PY" scripts/update_storage_guides.py; echo "== 보관법 exit=$?"
  echo "== $(date '+%F %T') 지역특산물·농가맛집 수집"; "$PY" scripts/update_local_knowledge.py; echo "== 지역정보 exit=$?"
  echo "== $(date '+%F %T') 쇼핑커넥트 발급 후보 목록"; "$PY" scripts/build_connect_candidates.py; echo "== 후보목록 exit=$?"
  # 식품정보24 일반식품 API는 114만 건을 10건씩만 제공해 주간 전체 수집은 하지 않는다 (2026-10-27)
} >> "$LOG" 2>&1
