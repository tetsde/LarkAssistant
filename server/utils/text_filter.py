import re
from flashtext import KeywordProcessor

class TextFilter:
    # Giới hạn "token" đầu vào (dùng word count để ước lượng nhanh)
    MIN_WORDS = 5
    MAX_WORDS = 1000  # ~1300 tokens

    def __init__(self):
        self.keyword_processor = KeywordProcessor()
        
        # Lọc các tin nhắn tán gẫu, rủ rê làm việc riêng, lãng phí thời gian trong giờ làm (Office Slacking/Chitchat)
        corporate_bad_phrases = [
            # 1. Ăn uống, cà phê, la cà
            "cà phê không", "trà sữa không", "đi nhậu không", "làm nháy không", "làm cốc bia",
            "nay ăn gì", "order đồ ăn", "đặt trà sữa", "đặt cơm", "ăn vặt không", "ăn chiều",
            "xuống lầu hút thuốc", "đi cf", "nhậu nhẹt", "tối nay đi đâu", "tối nay nhậu",
            
            # 2. Mua sắm, cá nhân
            "book vé", "chốt đơn", "mua sắm", "shopping", "mua shopee", "săn sale", 
            "chốt deal", "đi đu idol", "đu trend", "săn vé máy bay",
            
            # 3. Chơi game, giải trí
            "chơi game", "leo rank", "đánh liên minh", "chơi bida", "đánh cờ", 
            "chơi cờ tướng", "xem bóng đá", "xem đá banh", "xem kèo", "soi kèo", 
            "chơi cá độ", "chơi bài", "đánh bài", "đi hát", "hát karaoke", "đi massage",
            
            # 4. Tám chuyện, lướt mạng xã hội
            "đi quẩy", "buôn dưa lê", "tám chuyện", "tám nhảm", "rảnh không",
            "xem phim", "xem top top", "lướt tiktok", "lướt phây", "lướt facebook", "xem youtube"
        ]
        
        for phrase in corporate_bad_phrases:
            # Không cần biến thành [CENSORED] nữa, chỉ cần add vào dict để detect
            self.keyword_processor.add_keyword(phrase)

    def validate_and_clean(self, text: str) -> str:
        if not text or not text.strip():
            raise ValueError("Tin nhắn không được để trống.")
            
        # --- BƯỚC 1: LỌC BẰNG REGEX (Dynamic patterns) ---
        # Loại bỏ các spam ký tự (VD: !!!!! -> !)
        cleaned = re.sub(r'([!@#$%^&*?])\1+', r'\1', text)
        # Dọn dẹp khoảng trắng
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # --- BƯỚC 2: VALIDATE MIN/MAX TOKENS (IN) ---
        word_count = len(cleaned.split())
        if word_count < self.MIN_WORDS:
            raise ValueError("Tin nhắn quá ngắn. Vui lòng cung cấp thêm thông tin.")
        if word_count > self.MAX_WORDS:
            raise ValueError(f"Tin nhắn quá dài ({word_count} từ). Giới hạn tối đa là {self.MAX_WORDS} từ.")

        # --- BƯỚC 3: DETECT PHRASES CỐ ĐỊNH BẰNG FLASHTEXT ---
        found_keywords = self.keyword_processor.extract_keywords(cleaned)
        if found_keywords:
            # Nếu bắt được bất kì từ nào trong danh sách -> Cắt cổ ngay lập tức
            # Dùng set() để loại bỏ các từ bị trùng lặp khi báo lỗi
            detected_words = ", ".join(set(found_keywords))
            raise ValueError(f"Yêu cầu không hợp lệ. Vui lòng tập trung vào công việc! (Phát hiện cụm từ vi phạm: {detected_words})")
        
        return cleaned

text_filter = TextFilter()
