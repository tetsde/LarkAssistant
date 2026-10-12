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
        """Kiểm tra và chuẩn hoá đầu vào tin nhắn từ người dùng."""
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

    def clean_output(self, text: str) -> str:
        """
        Làm sạch nội dung đầu ra từ LLM:
          - Loại bỏ các thẻ trích dẫn RAG/WeKnora: <kb ... />, </kb>, <doc ... />, v.v.
          - Dọn dẹp khoảng trắng dư thừa, dấu câu bị hở do việc xóa thẻ.
          - Giữ nguyên cấu trúc định dạng Markdown (xuống dòng, bảng biểu, danh sách).
        """
        if not text or not isinstance(text, str):
            return ""

        cleaned = text

        # 1. Xoá các thẻ XML/HTML trích dẫn RAG (kb, doc, chunk, source, citation)
        cleaned = re.sub(
            r'<(?:kb|doc|chunk|source|citation)\b[^>]*\/>',
            '',
            cleaned,
            flags=re.IGNORECASE
        )
        cleaned = re.sub(
            r'<(?:kb|doc|chunk|source|citation)\b[^>]*>.*?<\/(?:kb|doc|chunk|source|citation)>',
            '',
            cleaned,
            flags=re.IGNORECASE | re.DOTALL
        )
        cleaned = re.sub(
            r'<\/?(?:kb|doc|chunk|source|citation)\b[^>]*>',
            '',
            cleaned,
            flags=re.IGNORECASE
        )

        # 2. Xóa khoảng trắng đứng trước dấu câu do việc xóa thẻ để lại (vd: "abc , xyz" -> "abc, xyz")
        cleaned = re.sub(r'[ \t]+([,.:;?!])', r'\1', cleaned)

        # 3. Chuẩn hóa khoảng trắng ngang (nhiều dấu cách liền nhau -> 1 dấu cách, giữ nguyên \n)
        cleaned = re.sub(r'[^\S\r\n]+', ' ', cleaned)

        # 4. Xóa khoảng trắng ở cuối mỗi dòng
        cleaned = re.sub(r'[ \t]+\n', '\n', cleaned)

        # 5. Rút gọn nhiều dòng trống liên tiếp (3 \n trở lên -> tối đa 2 \n)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

        return cleaned.strip()

    def extract_kb_citations(self, text: str) -> list[dict[str, str]]:
        """
        Trích xuất danh sách metadata các tài liệu RAG từ thẻ <kb ... /> nếu cần dùng riêng.
        """
        if not text or not isinstance(text, str):
            return []
        citations = []
        pattern = r'<kb\b([^>]*)\/?>'
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            attrs_str = match.group(1)
            attrs = {}
            for attr_match in re.finditer(r'(\w+)=["\']([^"\']*)["\']', attrs_str):
                attrs[attr_match.group(1)] = attr_match.group(2)
            if attrs:
                citations.append(attrs)
        return citations

    # Aliases
    filter_output = clean_output
    sanitize_output = clean_output


text_filter = TextFilter()

