#!/bin/bash
# 프론트엔드 빌드 스크립트 (Aider 없이 자동 실행)
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd /Users/mom/integrated_system/ui_ux

# npm 패키지 설치 확인 (최초 1회)
if [ ! -d "node_modules" ]; then
    npm install
fi

# 프론트엔드 빌드 실행 (dist 폴더 생성/업데이트)
npm run build

echo "[$(date)] 프론트엔드 빌드 완료" >> /Users/mom/integrated_system/var/build_daily.log
