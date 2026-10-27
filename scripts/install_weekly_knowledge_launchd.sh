#!/bin/bash
# 매주 월요일 오전 10시 20분 레시피·보관법 수집 예약 등록 (한 번만 실행)
# Mac이 잠자기 중이면 깨어난 뒤 실행됩니다.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=kr.integrated.weeklyknowledge
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
chmod +x "$ROOT/scripts/run_weekly_knowledge.sh"
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/var/logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$ROOT/scripts/run_weekly_knowledge.sh</string></array>
  <key>StartCalendarInterval</key><dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>20</integer></dict>
  <key>StandardOutPath</key><string>$ROOT/var/logs/weekly_knowledge_launchd.out</string>
  <key>StandardErrorPath</key><string>$ROOT/var/logs/weekly_knowledge_launchd.err</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "등록 완료: 매주 월요일 10:20 → var/recipes/recipes.json, var/knowledge/storage_guides.json"
launchctl print "gui/$(id -u)/$LABEL" | grep -E "state|run interval|Weekday" || true
echo "지금 한 번 시험 실행하려면: launchctl kickstart -k gui/$(id -u)/$LABEL"
