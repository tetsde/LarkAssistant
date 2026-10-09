import json, os, requests, time
from dotenv import load_dotenv
load_dotenv()
jev_api = os.getenv('jev_api')

data = []
with open('multihop.json', 'r') as f:
    for line in f:
        if line.strip(): data.append(json.loads(line))

all_intents = ['update_project_status', 'rag_doc_search', 'chitchat_direct_answer', 'escalate_issue', 'reject_access_denied', 'execute_code_sandbox']
criteria = {i: i for i in all_intents}

low_conf = 0
wrong_intent = 0
total = min(len(data), 5) # Test 5 items to not waste too much JEV money, or just test all 20? Let's test 10.
print("Testing 10 items for JEV:")
for i in range(10):
    item = data[i]
    state_text = json.dumps(item['context'], ensure_ascii=False)
    gt_intent = item['output']['intent']
    
    payload = {
        "state": state_text,
        "model": "jev-latest",
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "Phân loại intent của tin nhắn dựa trên ngữ cảnh.",
                "criteria": criteria
            }
        }
    }
    try:
        res = requests.post("https://api.typesafe.ai/v1/systemone", headers={"Authorization": f"Bearer {jev_api}", "Content-Type": "application/json"}, json=payload)
        ans = res.json()["answers"]["intent"]
        pred = ans["choice"]
        conf = ans["confidence"]
        
        status = "CORRECT"
        if conf <= 0.8:
            status = f"SKIPPED (conf={conf})"
            low_conf += 1
        elif pred != gt_intent:
            status = f"WRONG (pred={pred}, gt={gt_intent})"
            wrong_intent += 1
            
        print(f"ID: {item['id']} | GT: {gt_intent} | Pred: {pred} | Conf: {conf:.2f} | Status: {status}")
    except Exception as e:
        print("Err:", e)
    time.sleep(0.5)

print(f"Low conf: {low_conf}, Wrong intent: {wrong_intent}")
