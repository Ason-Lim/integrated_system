#!/usr/bin/env bash
# 내부 전용: 127.0.0.1 바인딩. 외부 접근이 필요하면 VPN/사내망 + 리버스 프록시 인증을 앞에 두세요.
cd "$(dirname "$0")" && exec python -m uvicorn b2b.app:app --host 127.0.0.1 --port 8100
