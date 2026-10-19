"""테스트는 임시 DB·예시 마켓·LLM 비활성 상태에서 실행 (모듈 import 전에 환경 고정)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_d = Path(tempfile.mkdtemp(prefix="cp_test_"))
os.environ.update({
    "CORE_DB_URL": f"sqlite:///{_d / 'core.sqlite3'}",
    "B2B_DB_URL": f"sqlite:///{_d / 'b2b.sqlite3'}",
    "B2B_ACCESS_TOKEN": "test-token", "LLM_PROVIDER": "none", "SAMPLE_MARKET": "1",
})
for k in ("COUPANG_ACCESS_KEY", "NAVER_ENABLED", "COMMERCE_AI_PATH", "FOOD_NLU_PATH"):
    os.environ.pop(k, None)
