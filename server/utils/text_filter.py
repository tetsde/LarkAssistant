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

    @staticmethod
    def strip_markdown(text: str) -> str:
        """
        Loại bỏ cú pháp Markdown (.md) để trả lời dưới dạng Plain Text thuần túy:
          - Loại bỏ khối code ```code``` và inline code `code`.
          - Loại bỏ ký tự in đậm (**text**, __text__) và in nghiêng (*text*, _text_).
          - Loại bỏ tiêu đề Markdown (#, ##, ###) và bullet points (*, -, +).
          - Chuyển đổi Markdown link [text](url) -> text (url).
        """
        if not text or not isinstance(text, str):
            return ""

        # 1. Khối code ```code``` -> giữ lại nội dung code bên trong
        cleaned = re.sub(r'```(?:[a-zA-Z0-9_-]+)?\n?(.*?)\n?```', r'\1', text, flags=re.DOTALL)
        # 2. Inline code `code` -> code
        cleaned = re.sub(r'`([^`]+)`', r'\1', cleaned)
        # 3. In đậm / in nghiêng: ***text***, **text**, *text*, ___text___, __text__, _text_
        cleaned = re.sub(r'\*\*\*(.*?)\*\*\*', r'\1', cleaned)
        cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned)
        cleaned = re.sub(r'(?<!\w)\*(.*?)\*(?!\w)', r'\1', cleaned)
        cleaned = re.sub(r'___(.*?)___', r'\1', cleaned)
        cleaned = re.sub(r'__(.*?)__', r'\1', cleaned)
        cleaned = re.sub(r'(?<!\w)_(.*?)(?![\w/])', r'\1', cleaned)
        # 4. Tiêu đề Markdown: #, ##, ###
        cleaned = re.sub(r'^[ \t]*#{1,6}\s*', '', cleaned, flags=re.MULTILINE)
        # 5. Ký tự gạch đầu dòng danh sách: *, -, +
        cleaned = re.sub(r'^[ \t]*[\*\-\+]\s+', '', cleaned, flags=re.MULTILINE)
        # 6. Markdown links [text](url) -> text (url)
        cleaned = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\1 (\2)', cleaned)
        cleaned = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', cleaned)
        return cleaned

    @staticmethod
    def strip_greetings(text: str) -> str:
        """
        Loại bỏ lời chào khách sáo ở đầu tin nhắn (Chào bạn, Chào em, Chào [Tên], Hi..., Xin chào...).
        Chỉ giữ lại nội dung thực tế hoặc lời xưng hô tự nhiên trong câu.
        """
        if not text or not isinstance(text, str):
            return ""

        greeting_pattern = (
            r'^(?:(?:Xin\s+)?Chào(?!\s+mừng)|Hi|Hello)\b'
            r'(?:\s+(?:em|anh|chị|bạn|mọi người|[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)?))?'
            r'(?:[,:\-–!]\s*|\s*\n+\s*|\s+)'
        )
        m = re.match(greeting_pattern, text, flags=re.IGNORECASE)
        if m:
            rest = text[m.end():].strip()
            if rest:
                return rest[0].upper() + rest[1:]
            return rest
        return text

    def clean_output(self, text: str, strip_md: bool = True, strip_greet: bool = True) -> str:
        """
        Làm sạch nội dung đầu ra từ LLM:
          - Loại bỏ các thẻ trích dẫn RAG/WeKnora: <kb ... />, </kb>, <doc ... />, v.v.
          - Loại bỏ các ngoặc trích dẫn nguồn RAG ([Tài liệu: ...], [Cập nhật hội thoại: ...]).
          - Loại bỏ định dạng Markdown (.md) nếu strip_md=True (trả lời Plain Text).
          - Loại bỏ lời chào khách sáo ở đầu tin nhắn nếu strip_greet=True.
          - Dọn dẹp khoảng trắng dư thừa, chuẩn hóa dấu câu và ngắt dòng.
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

        # 1.1 Xoá các thẻ ngoặc trích dẫn nguồn RAG nếu LLM vô tình sinh ra (vd: [Cập nhật hội thoại: ...], [Tài liệu: ...])
        cleaned = re.sub(
            r'\[(?:Cập nhật hội thoại|Tài liệu|Nguồn|Source|Chunk ID|Document)[^\]]*\]',
            '',
            cleaned,
            flags=re.IGNORECASE
        )

        # 1.2 Loại bỏ cú pháp Markdown (.md) theo yêu cầu người dùng
        if strip_md:
            cleaned = self.strip_markdown(cleaned)

        # 1.3 Loại bỏ lời chào khách sáo mở đầu câu nếu có
        if strip_greet:
            cleaned = self.strip_greetings(cleaned)

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

