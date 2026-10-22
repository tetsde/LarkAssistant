# HiLark — Điểm Trọng Yếu Cần Nắm Vững Khi Bị Phản Biện

> Tài liệu này phân tích **6 điểm đặc biệt, khó, và dễ bị phản biện nhất** trong kiến trúc bảo mật của HiLark.

---

## 🔴 Điểm 1: Hybrid Gating — Kết hợp Probabilistic AI (JEV) + Deterministic Rule Engine

### Vì sao đây là điểm **khó nhất** của hệ thống?

Hầu hết hệ thống bảo mật chỉ chọn một trong hai:
- Dùng AI → linh hoạt nhưng không đảm bảo 100%
- Dùng rule-based → chắc chắn nhưng cứng nhắc

HiLark **kết hợp cả hai theo thứ tự pipeline có chủ ý**:

```
Input ──► [JEV Forbidden Intent Gate] ──► [Unified Rule Engine] ──► Output
              (probabilistic, NLU)             (deterministic, regex)
                  Tầng 3                            Tầng 4
```

### Chi tiết kỹ thuật

**JEV (Tầng 3 — Input Gate):**
- Dùng AI NLU để bắt **intent** (ý định) → hiểu ngữ nghĩa, tiếng lóng, euphemism
- Threshold: `prob_forbidden >= 0.65` (choice FORBIDDEN) hoặc `>= 0.70` (pure prob)
- Fallback chain: `keyword_match → JEV API → exception_keyword_fallback`
- Quyết định: **Silent Drop** (không trả lời, không báo lỗi cho user)

**Rule Engine (Tầng 4 — Knowledge Sanitizer):**
- 100% in-memory, zero AI call (0ms độ trễ CPU)
- **Thực thi TRƯỚC JEV Relevance Filter:** Lọc sạch nhãn cấm ngay trên RAM trước khi gửi chunks qua mạng sang API chấm điểm JEV, triệt tiêu nguy cơ rò rỉ dữ liệu mật và tiết kiệm token
- Canonical Property Mapping: "lương" → {salary, compensation, payroll, wage}
- Vietnamese Word-Boundary Regex (accented + unaccented)
- Token Intersection để tránh false positive: "fee" trong "feedback", "gia" trong "giai_doan"
- Quyết định: Drop từng chunk/claim vi phạm, downgrade context nếu rỗng

### Phân biệt vai trò

| | JEV Gate (Tầng 3) | Rule Engine (Tầng 4) |
|---|---|---|
| **Input** | Raw user query | Retrieved chunks + claims |
| **Đối tượng** | Ý định người hỏi | Nội dung tri thức trả về |
| **Công nghệ** | AI/NLU probabilistic | Deterministic regex |
| **Thời điểm chạy** | Trước RAG retrieval | Ngay sau retrieval, TRƯỚC JEV Filter |
| **Vi phạm → hành động** | Dừng pipeline hoàn toàn | Drop item, tiếp tục phần còn lại |

### Trả lời phản biện

> "Tại sao không chỉ dùng Rule Engine?"

Rule Engine chỉ bắt được keyword xuất hiện trực tiếp. Không hiểu:
- "Anh ấy kiếm được bao nhiêu một tháng?" → không có chữ "lương"
- "Ting ting của team mình thế nào?" → tiếng lóng
- "Củ tháng này ra sao?" → euphemism

JEV hiểu **semantic intent** → bắt được các biến thể này.

> "Tại sao không chỉ dùng JEV?"

AI có thể sai (false negative). Rule Engine là **lớp đảm bảo cuối cùng** — JEV bỏ sót thì Rule Engine vẫn drop chunks/claims vi phạm trước khi đưa vào Gemini.

---

## 🔴 Điểm 2: Zero Auto-Reply + HITL (Human-in-the-Loop) cho Confidential Context

### Vì sao thiết kế này đặc biệt?

Khi Rule Engine xóa hết context, chatbot thông thường sẽ:
- Nói "Tôi không có thông tin" → **vô tình xác nhận thông tin nhạy cảm tồn tại**
- Hallucinate → **rủi ro cao**

HiLark chọn: **không trả lời gì trong nhóm**, thay vào đó DM owner:

```
Empty Context Detected
        │
        ▼
  [DRAFT_PENDING_APPROVAL]
        │
        ▼
  DM Owner → "Có câu hỏi nhạy cảm, duyệt không?"
        │
        ▼
  approve → Bot gửi vào nhóm | discard → Im lặng hoàn toàn
```

### Trả lời phản biện

> "Latency của HITL quá cao?"

By design: thông tin confidential không thể có SLA real-time. Owner chủ động duyệt.

> "Nếu owner không online thì sao?"

Draft tồn trong MongoDB (`PENDING`). Khi owner quay lại DM bot và gõ "duyệt" → lấy draft mới nhất và gửi. Không mất dữ liệu.

> "Owner Anti-Loop Shield là gì?"

Khi owner nhắn trong nhóm, bot không auto-reply. Tránh vòng lặp: bot reply → owner nhắn lại → bot reply...

---

## 🟠 Điểm 3: RAG Hard Isolation — Per-Chat Knowledge Boundary

Mỗi nhóm chat có `ChatScopeRecord` với `knowledge_ids` và `project_tag` riêng. WeKnora **chỉ query trong KB được gán**, không phải toàn bộ hệ thống.

**Global Claims vs Scoped Claims:**
```python
# MongoDB filter — chỉ lấy claims của nhóm này + claims của project + global
scope_or = [{"scope_type": "global"}]
if chat_id:
    scope_or.append({"chat_id": chat_id})
if project_tag:
    scope_or.append({"project_tag": project_tag})
query = {"$or": scope_or}
```

- **Tag Retention Guard:** Khi đồng bộ từ Lark Base (`scope_service.py`), `project_tag` được bảo toàn (`raw_tag or existing_tag`) giúp nhóm không bao giờ bị mất phân vùng dữ liệu dù bản ghi Base thiếu cột này.
- **Rule Engine Lọc Toàn Diện:** Dù là Scoped Claims hay Global Claims, tất cả đều phải đi qua `RuleEngine.sanitize()` theo `forbidden_labels` của nhóm hiện tại trước khi ghép ngữ cảnh.

---

## 🟠 Điểm 4: Dynamic Forbidden Labels — Zero-Code Label Management

Admin thêm nhãn cấm trên **Lark Base UI** (multi-select field), không cần deploy code:

```
Lark Base: forbidden_labels = ["Ngân sách", "Thầu phụ", "NDA"]
                    ↓
Rule Engine: _build_matchers() → compile regex on-the-fly
                    ↓
Áp dụng ngay từ chat tiếp theo
```

Label bất kỳ chưa có trong canonical map → tự động build accented + unaccented regex.

**Performance:** In-memory regex compile < 1ms cho < 20 nhãn. Không query DB, không gọi API.

---

## 🟡 Điểm 5: TextFilter Gating — Pre-AI Syntactic Filter

```
Raw Message → [TextFilter] → [GroupInactiveShield] → [JEV Gate] → Pipeline
```

Lọc: độ dài 2–1000 từ, ký tự đặc biệt, sticker/emoji. Tiết kiệm ~60-70% JEV API calls.

---

## 🟡 Điểm 6: Admin Whitelist & 403 Boundary

`routers/scope.py` = thin REST controller cho quản trị bên ngoài.

Luồng chat **không đi qua router** — gọi thẳng `scope_service` Python method (in-process, 0ms overhead). Không có network hop để bypass.

---

## 📊 Ma Trận Phòng Thủ

| Điểm | Độ Khó | Câu hỏi dễ bị hỏi nhất |
|---|---|---|
| **1. Hybrid JEV + Rule Engine** | ⭐⭐⭐⭐⭐ | "Tại sao không chỉ dùng một cái?" |
| **2. HITL Zero Auto-Reply** | ⭐⭐⭐⭐ | "Latency quá cao?" |
| **3. RAG Hard Isolation** | ⭐⭐⭐ | "Global claims có bị lọc không?" |
| **4. Dynamic Labels** | ⭐⭐⭐ | "Performance khi build matchers?" |
| **5. TextFilter Gating** | ⭐⭐ | "Tại sao cần layer này?" |
| **6. Admin Whitelist** | ⭐⭐ | "Bypass router được không?" |

---

## 🎯 Câu Trả Lời "Killer"

### "Hệ thống có chắc chắn không bao giờ leak data không?"
> Không hệ thống nào đảm bảo 100%. Nhưng HiLark triển khai **Defense-in-Depth 5 tầng** — để leak cả 3 tầng cuối (JEV Gate + Rule Engine + HITL) cùng lúc là cực kỳ khó trong môi trường thực tế.

### "JEV có thể bị adversarial prompt không?"
> Có thể. Đó là lý do Rule Engine (Tầng 4) **hoạt động độc lập**, không phụ thuộc JEV. Kể cả JEV bị bypass, Rule Engine vẫn xóa chunks/claims vi phạm trước khi đưa vào Gemini.

### "Nếu Gemini hallucinate ra thông tin lương thì sao?"
> Gemini chỉ nhận context đã qua Rule Engine (không có chunk/claim lương). Gemini không thể "biết" lương nếu không có trong context. Trong môi trường nội bộ với data độc quyền, hallucination về thông tin này không áp dụng.
