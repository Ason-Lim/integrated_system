#!/usr/bin/env python3
"""기존 smallbiz-monitor / gift_trend_analyzer 의 SQLite DB 에서 gift_bids 만 가져온다.

    python scripts/import_legacy_gift_db.py ~/anti_online/data/smallbiz_programs.db

- 소상공인 지원사업(programs) 테이블은 가져오지 않는다 (통합 시스템에서 삭제된 기능).
- gift_bids 는 database.py 시드와 core_crawler.py 시뮬레이션으로 채워진 데이터라
  '미검증 기존 데이터(legacy_unverified)'로 저장되고, 목록·트렌드 기본값에서 제외된다.
- Postgres(Render) 에 있던 데이터는 먼저 SQLite 로 내보내거나 CSV 로 받아 콘솔에서 업로드하세요.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from b2b.gift_monitor.collectors import import_legacy_db, legacy_status_counts  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    n = import_legacy_db(sys.argv[1])
    print(f"가져온 공고 {n}건 (모두 '미검증 기존 데이터'로 표시) · 상태별 {legacy_status_counts()}")
