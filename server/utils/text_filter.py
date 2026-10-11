import re


class TextFilter:
    """
    Syntactic Sanitizer & Input Validator
    =====================================
    Nhiệm vụ:
      - Loại bỏ ký tự spam lặp, chuẩn hóa khoảng trắng.
      - Kiểm tra độ dài từ tối thiểu và tối đa.
      - KHÔNG lọc theo từ điển cụm từ (để tránh chặn nhầm nghiệp vụ, việc nhận diện ngữ nghĩa bàn giao cho JEV).
    """
    MIN_WORDS = 2
    MAX_WORDS = 1000  # ~1300 tokens

    def __init__(self):
        pass

    def validate_and_clean(self, text: str) -> str:
        if not text or not text.strip():
            raise ValueError("Tin nhắn không được để trống.")

        # --- BƯỚC 1: LỌC BẰNG REGEX (Dynamic patterns) ---
        # Loại bỏ các spam ký tự liên tiếp (VD: !!!!! -> !)
        cleaned = re.sub(r'([!@#$%^&*?])\1+', r'\1', text)
        # Dọn dẹp khoảng trắng dư thừa
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        # --- BƯỚC 2: VALIDATE MIN/MAX TOKENS ---
        word_count = len(cleaned.split())
        if word_count < self.MIN_WORDS:
            raise ValueError("Tin nhắn quá ngắn. Vui lòng cung cấp thêm thông tin.")
        if word_count > self.MAX_WORDS:
            raise ValueError(f"Tin nhắn quá dài ({word_count} từ). Giới hạn tối đa là {self.MAX_WORDS} từ.")

        return cleaned


text_filter = TextFilter()

