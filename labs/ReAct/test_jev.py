import os
import requests
from dotenv import load_dotenv

load_dotenv()
jev_api = os.getenv("jev_api")
url = "https://api.typesafe.ai/v1/systemone"
headers = {
    "Authorization": f"Bearer {jev_api}",
    "Content-Type": "application/json"
}
all_tools = ["knowledge_search", "python_data_sandbox"]
payload = {
    "state": "test",
    "model": "jev-latest",
    "questions": {
        "target_tool": {
            "type": "choice",
            "instructions": "test",
            "criteria": {t: t for t in all_tools}
        }
    }
}
res = requests.post(url, headers=headers, json=payload, timeout=30)
print(res.status_code)
print(res.text)
