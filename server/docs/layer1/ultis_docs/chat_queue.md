# 📘 BÓC TÁCH KỸ THUẬT: `utils/chat_queue.py`
> **HiLark Server** — Module điều phối hàng đợi thông minh & gom tin nhắn gõ ngắt quãng.  
> **Vị trí file:** [`server/utils/chat_queue.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/chat_queue.py) (335 dòng, 14.5 KB).

---

## 🧭 1. VAI TRÒ VÀ BÀI TOÁN CỐT LÕI GIẢI QUYẾT

Trong môi trường làm việc trên Lark Suite, người dùng thường có hai thói quen phổ biến:
1. **Gõ tin nhắn ngắt quãng (Burst typing):** Thay vì viết một đoạn dài, người dùng bấm Enter liên tục 3–4 lần:
   > *"Alo bạn ơi"* [Enter]  
   > *"Cho mình hỏi tiến độ dự án Sàn"* [Enter]  
   > *"Hôm nay đã xong chưa?"* [Enter]  
   *Nếu không có bộ gom tin, hệ thống sẽ kích hoạt 3 lần pipeline AI, trả lời 3 câu cụt ngủn và gây lãng phí quota.*
2. **Hỏi dồn dập (Spam / Chạm trần Rate Limit):** Nhiều thành viên gửi tin nhắn liên tục hoặc một người hỏi liên hồi làm cạn kiệt Token/RPM của Gemini AI, gây lỗi `429 Too Many Requests`.

Module [`server/utils/chat_queue.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/chat_queue.py) ra đời để giải quyết dứt điểm 2 bài toán trên thông qua cơ chế:
* **Gom dòng tự động (Debounce):** Đợi người dùng gõ xong mới xử lý một thể.
* **Hàng đợi điều tiết tốc độ (Throttled Queue):** Làm mượt dòng lưu lượng, giãn cách âm thầm (Silent Throttling) và giới hạn luồng chạy song song.

---

## 🏗️ 2. KIẾN TRÚC 3 THÀNH PHẦN CỐT LÕI

Toàn bộ file được cấu trúc thành 3 lớp đối tượng có quan hệ móc nối chặt chẽ:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   ChatQueueService                                      │
│                           (Điểm điều phối dịch vụ tổng thể)                             │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                      ┌──────────────────────┴──────────────────────┐
                      ▼                                             ▼
          ┌───────────────────────┐                     ┌───────────────────────┐
          │    MessageDebouncer   │                     │   ThrottledChatQueue  │
          ├───────────────────────┤                     ├───────────────────────┤
          │ • Bộ đệm gom tin theo │ ───[on_flush]────>  │ • Hàng đợi 100 slots  │
          │   (chat_id, user_id)  │    (ChatQueueItem)  │ • Timeout chờ 2s      │
          │ • Cửa sổ chờ 1.75s    │                     │ • Giãn cách 4.0s/user │
          │ • Nối text bằng '\\n'  │                     │ • Semaphore(max=3)    │
          └───────────────────────┘                     └───────────┬───────────┘
                                                                    │
                                                                    ▼
                                                         process_chat_pipeline()
                                                           (Chuyển sang Layer 2)
```

---

## 🔬 3. CHI TIẾT KỸ THUẬT TỪNG CLASS (CODE-LEVEL)

### A. Class `MessageDebouncer` — Bộ gom tin nhắn ngắt quãng
- **Vị trí:** [`server/utils/chat_queue.py:L27-119`](file:///Users/hoainam/Desktop/HiLark/server/utils/chat_queue.py#L27-L119)
- **Cấu trúc dữ liệu nội bộ:**
  * `self._buffers: Dict[Tuple[str, str], List[LarkMessage]]`: Lưu danh sách tin nhắn đang gom theo cặp khóa `(chat_id, sender_id)`. Đảm bảo gom riêng từng người trong từng nhóm, không bị lẫn người này sang người khác.
  * `self._timers: Dict[Tuple[str, str], asyncio.TimerHandle]`: Quản lý bộ đếm thời gian thực thi cho từng người dùng.
  * `self._lock = asyncio.Lock()`: Khóa bất đồng bộ chống xung đột tranh chấp luồng (Race Condition) khi nhiều tin nhắn tới đồng thời.

#### Thuật toán Gom tin (`push` và `_flush`):
1. **Khi có tin nhắn mới tới (`push`):**
   ```python
   async with self._lock:
       # 1. Hủy timer cũ nếu người dùng vẫn đang gõ tiếp
       old_timer = self._timers.get(key)
       if old_timer and not old_timer.cancelled():
           old_timer.cancel()
           
       # 2. Đưa tin nhắn vào buffer
       self._buffers[key].append(msg)
       
       # 3. Kích hoạt bộ đếm 1.75s mới
       loop = asyncio.get_running_loop()
       self._timers[key] = loop.call_later(
           self.debounce_seconds,
           lambda: asyncio.create_task(self._flush(key, ...))
       )
   ```
2. **Khi hết thời gian chờ 1.75s (`_flush`):**
   * Lấy toàn bộ danh sách tin nhắn ra khỏi `_buffers[key]`.
   * Trích xuất văn bản hợp lệ, ghép lại bằng ký tự xuống dòng: `combined_text = "\n".join(valid_texts)`.
   * Lấy mã tin nhắn cuối cùng làm mỏ neo trả lời: `anchor_message_id = last_msg.message_id`.
   * Đóng gói thành đối tượng dữ liệu [`ChatQueueItem`](file:///Users/hoainam/Desktop/HiLark/server/models/chat_queue.py) và kích hoạt callback `on_flush(item)`.

---

### B. Class `ThrottledChatQueue` — Hàng đợi điều tiết & Chống nghẽn hạ tầng
- **Vị trí:** [`server/utils/chat_queue.py:L121-236`](file:///Users/hoainam/Desktop/HiLark/server/utils/chat_queue.py#L121-L236)
- **Thông số cấu hình:**
  * `max_size = 100`: Sức chứa tối đa của hàng đợi `asyncio.Queue`.
  * `cooldown_seconds = 4.0s`: Thời gian giãn cách tối thiểu giữa 2 lần AI xử lý tin nhắn của cùng một người.
  * `max_concurrent = 3`: Giới hạn tối đa 3 tiến trình AI chạy cùng lúc trên toàn server thông qua `asyncio.Semaphore(3)`.
  * `enqueue_timeout = 2.0s`: Thời gian chờ tối đa khi hàng đợi bị đầy.

#### 1. Cơ chế xếp hàng & Xử lý tràn Queue (Giai đoạn 1):
```python
async def enqueue(self, item: ChatQueueItem) -> bool:
    try:
        # Chờ tối đa 2.0 giây để có chỗ trống trong hàng đợi
        await asyncio.wait_for(self._queue.put(item), timeout=self.enqueue_timeout)
        return True
    except asyncio.TimeoutError:
        # HÀNG ĐỢI ĐẦY QUÁ 2.0 GIÂY:
        # Ghi log ERROR chi tiết, hủy tin mới, BẢO TOÀN tin cũ trong queue!
        logger.error(
            f"❌ [QUEUE OVERFLOW] Hàng đợi Layer 1 đã đầy ({self._queue.qsize()}/{self.max_size}). "
            f"Đã chờ {self.enqueue_timeout}s nhưng không có chỗ trống! "
            f"Bỏ qua tin nhắn mới của '{item.user_name}' ({item.sender_id}) trong chat '{item.chat_id}'. "
            f"Tạm thời giữ nguyên các tin cũ trong hàng đợi."
        )
        return False
```

#### 2. Cơ chế Giãn cách âm thầm (Silent Throttling) trong Worker Loop:
* Worker ngầm chạy độc lập `_worker_loop()` liên tục lấy từng mục từ `self._queue.get()`.
* Đo lường thời gian: `elapsed = now - last_processed[sender_id]`.
* **Nếu `elapsed < 4.0s` và không phải là Chủ nhân (`not is_owner`):**
  * Hệ thống tính độ trễ cần bù: `delay = 4.0 - elapsed`.
  * Thực thi `await asyncio.sleep(delay)` để làm chậm luồng **một cách âm thầm trong nền**.
  * **Tuyệt đối không gửi tin nhắn cảnh báo rác vào nhóm chat** (tránh làm loãng cuộc trò chuyện).
* Cập nhật mốc thời gian: `self._last_user_processed[sender_id] = time.time()`.

#### 3. Chốt chặn tài nguyên Concurrency Semaphore:
* Mỗi tin nhắn sau khi qua cooldown sẽ được thực thi trong một tác vụ độc lập:
  ```python
  async def _process_with_semaphore(self, item: ChatQueueItem) -> None:
      async with self.semaphore: # Giới hạn tối đa 3 tác vụ
          await self.pipeline_executor(item)
  ```
* Ngăn chặn triệt để tình trạng nhiều nhóm chat hỏi cùng lúc làm nghẽn CPU hoặc cạn kiệt tài nguyên mạng của server.

---

### C. Class `ChatQueueService` — Điểm tích hợp & Bàn giao sang Layer 2
- **Vị trí:** [`server/utils/chat_queue.py:L237-335`](file:///Users/hoainam/Desktop/HiLark/server/utils/chat_queue.py#L237-L335)
- **Nhiệm vụ:** Là cầu nối trung tâm gắn kết `MessageDebouncer` $\rightarrow$ `ThrottledChatQueue` $\rightarrow$ [`process_chat_pipeline()`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py).

#### Luồng thực thi chi tiết:
1. `push_incoming_message()`: Tiếp nhận `LarkMessage` được chuyển từ `bot_service.py` đưa vào Debouncer.
2. `_on_debounced_ready(item)`: Khi Debouncer gom tin xong, gọi `self.queue.enqueue(item)`.
3. `_execute_pipeline(item)`: Khi đến lượt xử lý trong Queue, hàm này gọi thẳng vào động cơ chính của hệ thống:
   ```python
   result = await process_chat_pipeline(
       query=item.combined_text,
       sender=item.sender_id,
       channel=f"lark_{item.chat_type}",
       message_id=item.anchor_message_id,
       chat_id=item.chat_id,
       reply_to_lark=not item.is_owner, # Chủ nhân không reply vào nhóm
       user_name=item.user_name,
       responder_name=item.responder_name,
       role=item.role,
       is_owner=item.is_owner,
   )
   ```
4. **Phân tích kết quả thực thi & Ghi log trực quan:**
   * `forbidden_query`: In thông báo `[FORBIDDEN DROP]` — Kích hoạt Zero-response (im lặng tuyệt đối).
   * `group_inactive`: In thông báo `[GROUP INACTIVE]` — Nhóm tạm dừng hoạt động, bỏ qua tin nhắn.
   * `IGNORE`: In `[IGNORE]` — Tin rác, lời chào xã giao, không trả lời.
   * `MEMORY_ONLY`: In `[MEMORY_ONLY]` — Đã âm thầm trích xuất thông tin lưu vào MongoDB.
   * `DRAFT_PENDING_APPROVAL`: Soạn bản nháp và gửi riêng tới Sếp duyệt, không phát ngôn vào nhóm.
   * `REPLY_ONLY`: Trả lời trực tiếp nhân danh Sếp vào nhóm chat.

---

## 📋 4. BẢNG THAM SỐ CẤU HÌNH LIÊN QUAN

| Biến cấu hình trong `.env` | Giá trị mặc định | Giải thích kỹ thuật |
| :--- | :---: | :--- |
| `DEBOUNCE_DELAY_SECONDS` | `1.75` | Thời gian chờ gom tin nhắn ngắt dòng của một người dùng (giây). |
| `USER_COOLDOWN_SECONDS` | `4.0` | Giãn cách tối thiểu giữa 2 lần xử lý của cùng một người (giây). |
| `MAX_CONCURRENT_CHAT_PIPELINES`| `3` | Số lượng tác vụ AI được phép chạy song song tối đa toàn hệ thống. |
| `CHAT_QUEUE_MAX_SIZE` | `100` | Sức chứa tối đa của hàng đợi bộ nhớ ram. |
| `CHAT_QUEUE_ENQUEUE_TIMEOUT` | `2.0` | Thời gian chờ tối đa khi hàng đợi đầy trước khi hủy tin mới (giây). |

---

## 🛡️ 5. CƠ CHẾ ĐẶC QUYỀN CỦA CHỦ NHÂN (OWNER BYPASS)

Một nguyên tắc bất di bất dịch trong thiết kế Layer 1:
> **Chủ nhân (`is_owner=True`) KHÔNG BAO GIỜ bị hàng đợi chặn lại!**

* Khi Chủ nhân chat trong nhóm: Tin nhắn được đưa thẳng vào `process_chat_pipeline()` với cờ `reply_to_lark=False` (xem tại [`bot_service.py:L311-354`](file:///Users/hoainam/Desktop/HiLark/server/services/bot_service.py#L311-L354)).
* Mục đích: Hệ thống cần cập nhật trí nhớ động (`MEMORY_ONLY`) ngay lập tức từ mệnh lệnh của Sếp mà không phải xếp hàng chờ đợi, đồng thời bot không bao giờ nói leo vào nhóm thay lời Sếp.
