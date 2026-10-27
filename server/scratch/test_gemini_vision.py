import sys, os, base64, httpx
sys.path.insert(0, os.path.abspath("."))
from core.config import settings

api_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

dummy_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82'
b64 = base64.b64encode(dummy_png).decode()

payload = {
    "contents": [{
        "parts": [
            {"inlineData": {"mimeType": "image/png", "data": b64}},
            {"text": "Trong ảnh có gì? Trả lời ngắn gọn 1 câu."}
        ]
    }]
}

resp = httpx.post(url, json=payload, timeout=20)
print("Status:", resp.status_code)
if resp.status_code == 200:
    print("Resp:", resp.json()["candidates"][0]["content"]["parts"][0]["text"])
else:
    print("Error:", resp.text)
