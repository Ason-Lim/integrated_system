import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()

print(f"🔍 현재 .env에서 읽어온 키 (앞 12자): {API_KEY[:12]}...")
print(f"🔍 키 길이: {len(API_KEY)}자")
print(f"🔍 ASCII 여부: {API_KEY.isascii()}")

if not API_KEY:
    print("❌ 오류: .env 파일에 DEEPSEEK_API_KEY가 없습니다.")
    exit(1)

if not API_KEY.isascii():
    print("❌ 오류: API 키에 한글 등 비ASCII 문자가 포함되어 있습니다.")
    print("   .env 파일을 열어 실제 DeepSeek API 키로 교체해 주세요.")
    print("   발급처: https://platform.deepseek.com/api_keys")
    exit(1)

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")

try:
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "안녕하세요! 이 메시지가 잘 보이나요?"}
        ],
        max_tokens=100
    )
    print("\n✅ [성공] API 응답이 정상적으로 도착했습니다.")
    print("-" * 40)
    print(response.choices[0].message.content)
    print("-" * 40)
except Exception as e:
    print(f"\n❌ [실패] {type(e).__name__}: {e}")