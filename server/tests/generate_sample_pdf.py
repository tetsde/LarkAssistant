#!/usr/bin/env python3
"""
Script tạo tài liệu PDF mẫu về Dự án HiLark Assistant
======================================================
Vị trí: server/tests/generate_sample_pdf.py
Đầu ra: server/tests/du_an_mau_hilark.pdf
"""

import os
import sys
from datetime import datetime, timezone, timedelta

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Múi giờ Việt Nam
VIETNAM_TZ = timezone(timedelta(hours=7))


class NumberedCanvas(canvas.Canvas):
    """Canvas 2-pass tự động đánh số trang 'Trang X / Y' và footer chuyên nghiệp."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Arial", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        page_w, page_h = A4

        # Header (chỉ từ trang 2 trở đi)
        if self._pageNumber > 1:
            self.drawString(40, page_h - 30, "HiLark Assistant — Hồ sơ Kế hoạch Triển khai Dự án")
            self.drawRightString(page_w - 40, page_h - 30, "LƯU HÀNH NỘI BỘ")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(40, page_h - 34, page_w - 40, page_h - 34)

        # Footer
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(40, 40, page_w - 40, 40)

        now_str = datetime.now(VIETNAM_TZ).strftime("%d/%m/%Y %H:%M (GMT+7)")
        self.drawString(40, 28, f"Hệ thống HiLark AI • Xuất ngày: {now_str}")
        self.drawRightString(page_w - 40, 28, f"Trang {self._pageNumber} / {page_count}")

        self.restoreState()


def register_fonts():
    """Đăng ký font hỗ trợ tiếng Việt có dấu."""
    font_candidates = [
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "Arial"),
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "Arial-Bold"),
        ("/System/Library/Fonts/Supplemental/Arial Italic.ttf", "Arial-Italic"),
        ("/Library/Fonts/Arial.ttf", "Arial"),
        ("/Library/Fonts/Arial Bold.ttf", "Arial-Bold"),
    ]

    registered = set()
    for path, name in font_candidates:
        if os.path.exists(path) and name not in registered:
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                registered.add(name)
            except Exception as e:
                print(f"Không thể nạp font {name} từ {path}: {e}")

    # Fallback nếu thiếu Arial-Bold
    if "Arial" in registered and "Arial-Bold" not in registered:
        pdfmetrics.registerFont(TTFont("Arial-Bold", font_candidates[0][0]))


def create_project_pdf(output_path: str):
    register_fonts()

    # Khởi tạo Document
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=45,
        bottomMargin=50,
    )

    # Bảng màu chủ đạo (Enterprise Modern Palette)
    PRIMARY = colors.HexColor("#1E3A8A")     # Xanh Navy đậm
    SECONDARY = colors.HexColor("#0284C7")   # Xanh Cyan
    ACCENT = colors.HexColor("#0D9488")      # Xanh Ngọc
    DARK_TEXT = colors.HexColor("#0F172A")   # Chữ chính
    MUTED_TEXT = colors.HexColor("#475569")  # Chữ phụ
    BG_LIGHT = colors.HexColor("#F8FAFC")    # Nền sáng
    BORDER_COLOR = colors.HexColor("#E2E8F0")

    # Styles
    base_styles = getSampleStyleSheet()

    style_title = ParagraphStyle(
        "DocTitle",
        parent=base_styles["Heading1"],
        fontName="Arial-Bold",
        fontSize=20,
        leading=26,
        textColor=PRIMARY,
        alignment=0,
        spaceAfter=6,
    )

    style_subtitle = ParagraphStyle(
        "DocSubtitle",
        parent=base_styles["Normal"],
        fontName="Arial",
        fontSize=11,
        leading=16,
        textColor=MUTED_TEXT,
        spaceAfter=14,
    )

    style_h1 = ParagraphStyle(
        "SectionH1",
        parent=base_styles["Heading2"],
        fontName="Arial-Bold",
        fontSize=13,
        leading=18,
        textColor=PRIMARY,
        spaceBefore=14,
        spaceAfter=8,
    )

    style_body = ParagraphStyle(
        "BodyVN",
        parent=base_styles["Normal"],
        fontName="Arial",
        fontSize=9.5,
        leading=14,
        textColor=DARK_TEXT,
        spaceAfter=6,
    )

    style_table_cell = ParagraphStyle(
        "TableCell",
        parent=base_styles["Normal"],
        fontName="Arial",
        fontSize=8.5,
        leading=12,
        textColor=DARK_TEXT,
    )

    style_table_header = ParagraphStyle(
        "TableHeader",
        parent=base_styles["Normal"],
        fontName="Arial-Bold",
        fontSize=8.5,
        leading=12,
        textColor=colors.white,
    )

    story = []

    # =========================================================================
    # BANNER HEADER
    # =========================================================================
    badge_style = ParagraphStyle(
        "Badge",
        parent=base_styles["Normal"],
        fontName="Arial-Bold",
        fontSize=8,
        leading=10,
        textColor=PRIMARY,
    )
    story.append(Paragraph("DỰ ÁN CÔNG NGHỆ DOANH NGHIỆP • NĂM 2026", badge_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph("KẾ HOẠCH TRIỂN KHAI DỰ ÁN HILARK ASSISTANT", style_title))
    story.append(Paragraph("Nền tảng Quản trị Tri thức Phân cấp & Trợ lý Điều phối Tác nghiệp Đa kênh", style_subtitle))
    story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceAfter=14))

    # =========================================================================
    # 1. THÔNG TIN TỔNG QUAN (PROJECT OVERVIEW)
    # =========================================================================
    story.append(Paragraph("1. THÔNG TIN TỔNG QUAN DỰ ÁN", style_h1))
    
    overview_data = [
        [
            Paragraph("<b>Mã Dự án:</b>", style_table_cell),
            Paragraph("PRJ-HILARK-2026", style_table_cell),
            Paragraph("<b>Trạng thái:</b>", style_table_cell),
            Paragraph("<font color='#0D9488'><b>Đang triển khai (Active)</b></font>", style_table_cell),
        ],
        [
            Paragraph("<b>Chủ quản đầu tư:</b>", style_table_cell),
            Paragraph("Tập đoàn Công nghệ HiLark", style_table_cell),
            Paragraph("<b>Đối tác & Khách hàng:</b>", style_table_cell),
            Paragraph("Do Agency & Cowi Tech Group", style_table_cell),
        ],
        [
            Paragraph("<b>Project Lead:</b>", style_table_cell),
            Paragraph("Nguyễn Hoài Nam", style_table_cell),
            Paragraph("<b>Tech Lead:</b>", style_table_cell),
            Paragraph("Phan Anh Tuấn", style_table_cell),
        ],
        [
            Paragraph("<b>Ngày khởi động:</b>", style_table_cell),
            Paragraph("01/10/2026", style_table_cell),
            Paragraph("<b>Hạn hoàn thành (Deadline):</b>", style_table_cell),
            Paragraph("<b>30/11/2026</b> <i>(Đã chuẩn hoá GMT+7)</i>", style_table_cell),
        ],
        [
            Paragraph("<b>Ngân sách duyệt:</b>", style_table_cell),
            Paragraph("<b>650.000.000 VNĐ</b>", style_table_cell),
            Paragraph("<b>Phiên bản Core:</b>", style_table_cell),
            Paragraph("HiLark v2.1 (MongoDB Engine)", style_table_cell),
        ],
    ]

    t_overview = Table(overview_data, colWidths=[110, 150, 120, 135])
    t_overview.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.8, BORDER_COLOR),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t_overview)
    story.append(Spacer(1, 12))

    # =========================================================================
    # 2. MỤC TIÊU VÀ PHẠM VI TÍNH NĂNG (SCOPE & MODULES)
    # =========================================================================
    story.append(Paragraph("2. MỤC TIÊU & PHẠM VI TÍNH NĂNG CỐT LÕI", style_h1))
    story.append(Paragraph(
        "HiLark Assistant giải quyết bài toán phân mảnh thông tin trong giao tiếp doanh nghiệp "
        "bằng cách tự động phân tích hội thoại chat thành <b>Đồ thị Tri thức Phân cấp (Parent – Child Knowledge Graph)</b> "
        "kết hợp cơ chế lưu vết lịch sử biến động (Audit Trail).",
        style_body
    ))

    modules_data = [
        [
            Paragraph("Module / Phân hệ", style_table_header),
            Paragraph("Mô tả Tính năng", style_table_header),
            Paragraph("Công nghệ Chủ đạo", style_table_header),
            Paragraph("Tiến độ", style_table_header),
        ],
        [
            Paragraph("<b>1. LLM Extractor</b><br/>(Nhánh 1: Entities)", style_table_cell),
            Paragraph("Nhận diện 6 loại thực thể cốt lõi (Project, Person, Team, Customer, Feature, Document). Khử đồng tham chiếu tự động.", style_table_cell),
            Paragraph("Gemini 2.5 Flash, Regex Parser, UUIDv5", style_table_cell),
            Paragraph("<font color='#0D9488'><b>Hoàn tất 100%</b></font>", style_table_cell),
        ],
        [
            Paragraph("<b>2. Claims & Audit Engine</b><br/>(Nhánh 2: Facts)", style_table_cell),
            Paragraph("Trích xuất mệnh đề sự thật. Tự phát hiện biến động thay thế (replaces/superseded), lưu vết lịch sử thuộc tính.", style_table_cell),
            Paragraph("Pydantic v2, Motor Async, Timezone UTC+7", style_table_cell),
            Paragraph("<font color='#0D9488'><b>Hoàn tất 100%</b></font>", style_table_cell),
        ],
        [
            Paragraph("<b>3. Grounded QA Service</b><br/>(Bộ nhớ phân cấp)", style_table_cell),
            Paragraph("Trả lời câu hỏi tự nhiên dựa 100% trên Facts có căn cứ trích dẫn nguồn, kèm dòng thời gian biến động quá khứ.", style_table_cell),
            Paragraph("MongoDB (memories & claims), Gemini API", style_table_cell),
            Paragraph("<font color='#0D9488'><b>Hoàn tất 95%</b></font>", style_table_cell),
        ],
        [
            Paragraph("<b>4. Tích hợp Đa kênh</b><br/>(Lark Suite & Webhook)", style_table_cell),
            Paragraph("Đồng bộ tin nhắn 2 chiều từ Lark Chat, Lark Base và giao diện điều khiển nội bộ.", style_table_cell),
            Paragraph("FastAPI, Open Platform API", style_table_cell),
            Paragraph("<font color='#CA8A04'><b>Đang thực hiện (70%)</b></font>", style_table_cell),
        ],
    ]

    t_modules = Table(modules_data, colWidths=[120, 215, 110, 70])
    t_modules.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
    ]))
    story.append(t_modules)
    story.append(Spacer(1, 12))

    # =========================================================================
    # 3. CƠ CẤU NHÂN SỰ & PHÂN CÔNG (TEAM ROLES)
    # =========================================================================
    story.append(Paragraph("3. CƠ CẤU ĐỘI NGŨ & PHÂN CÔNG TÁC NGHIỆP", style_h1))

    team_data = [
        [
            Paragraph("Thành viên", style_table_header),
            Paragraph("Vai trò Đảm nhiệm", style_table_header),
            Paragraph("Nhiệm vụ Chính", style_table_header),
            Paragraph("Phân bổ", style_table_header),
        ],
        [
            Paragraph("<b>Nguyễn Hoài Nam</b>", style_table_cell),
            Paragraph("Project Lead / Product Owner", style_table_cell),
            Paragraph("Quản lý tiến độ tổng thể, định hướng nghiệp vụ, chuyển giao dự án qua đối tác Cowi.", style_table_cell),
            Paragraph("100% Full-time", style_table_cell),
        ],
        [
            Paragraph("<b>Phan Anh Tuấn</b>", style_table_cell),
            Paragraph("Tech Lead / Solution Architect", style_table_cell),
            Paragraph("Thiết kế kiến trúc 2 nhánh trích xuất, mô hình dữ liệu MongoDB và cơ chế Audit.", style_table_cell),
            Paragraph("100% Full-time", style_table_cell),
        ],
        [
            Paragraph("<b>Nguyễn Văn Nguyên</b>", style_table_cell),
            Paragraph("Senior Backend Engineer", style_table_cell),
            Paragraph("Phát triển các API trích xuất Async/Sync, MongoDB connector và tối ưu hóa hiệu năng.", style_table_cell),
            Paragraph("100% Full-time", style_table_cell),
        ],
        [
            Paragraph("<b>Trần Mỹ Linh</b>", style_table_cell),
            Paragraph("Lark Integration Specialist", style_table_cell),
            Paragraph("Xây dựng bot tương tác 2 chiều trên Lark Suite, xử lý webhook và tin nhắn sự kiện.", style_table_cell),
            Paragraph("80% Part-time", style_table_cell),
        ],
        [
            Paragraph("<b>Lê Quang Hải</b>", style_table_cell),
            Paragraph("QA & Data Evaluation Engineer", style_table_cell),
            Paragraph("Kiểm thử chất lượng bóc tách Entities/Facts, đánh giá độ chính xác của Grounded QA.", style_table_cell),
            Paragraph("80% Part-time", style_table_cell),
        ],
        [
            Paragraph("<b>Đỗ Thái Hoà</b>", style_table_cell),
            Paragraph("DevOps & Cloud Engineer", style_table_cell),
            Paragraph("Triển khai hạ tầng CI/CD, giám sát MongoDB Atlas và tối ưu hóa chi phí API.", style_table_cell),
            Paragraph("50% Part-time", style_table_cell),
        ],
    ]

    t_team = Table(team_data, colWidths=[105, 120, 210, 80])
    t_team.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SECONDARY),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
    ]))
    story.append(t_team)
    story.append(Spacer(1, 14))

    # =========================================================================
    # 4. KẾ HOẠCH MỐC THỜI GIAN & LỊCH TRÌNH (MILESTONES)
    # =========================================================================
    story.append(Paragraph("4. KẾ HOẠCH MỐC THỜI GIAN TRIỂN KHAI (MILESTONES)", style_h1))

    milestones_data = [
        [
            Paragraph("Mốc", style_table_header),
            Paragraph("Giai đoạn / Hạng mục Bàn giao", style_table_header),
            Paragraph("Thời hạn (Deadline)", style_table_header),
            Paragraph("Tình trạng", style_table_header),
        ],
        [
            Paragraph("<b>M1</b>", style_table_cell),
            Paragraph("Khảo sát kiến trúc, thiết lập kho lưu trữ MongoDB và kết nối Gemini Client", style_table_cell),
            Paragraph("10/10/2026", style_table_cell),
            Paragraph("<font color='#0D9488'><b>Đạt yêu cầu</b></font>", style_table_cell),
        ],
        [
            Paragraph("<b>M2</b>", style_table_cell),
            Paragraph("Hoàn thiện module bóc tách phân cấp (Entities & Claims) chuẩn hóa múi giờ Việt Nam", style_table_cell),
            Paragraph("12/10/2026", style_table_cell),
            Paragraph("<font color='#0D9488'><b>Đạt yêu cầu</b></font>", style_table_cell),
        ],
        [
            Paragraph("<b>M3</b>", style_table_cell),
            Paragraph("Triển khai Grounded QA truy vấn bộ nhớ thông minh, truy vết chuỗi Replaces", style_table_cell),
            Paragraph("25/10/2026", style_table_cell),
            Paragraph("<font color='#0284C7'>Đang thực hiện</font>", style_table_cell),
        ],
        [
            Paragraph("<b>M4</b>", style_table_cell),
            Paragraph("Tích hợp bot sự kiện đa kênh Lark và chạy kiểm thử chấp nhận người dùng (UAT)", style_table_cell),
            Paragraph("15/11/2026", style_table_cell),
            Paragraph("Theo kế hoạch", style_table_cell),
        ],
        [
            Paragraph("<b>M5</b>", style_table_cell),
            Paragraph("Đóng gói bàn giao Production cho đối tác Do Agency và Cowi Tech", style_table_cell),
            Paragraph("30/11/2026", style_table_cell),
            Paragraph("Theo kế hoạch", style_table_cell),
        ],
    ]

    t_milestones = Table(milestones_data, colWidths=[35, 290, 105, 85])
    t_milestones.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
    ]))
    story.append(t_milestones)
    story.append(Spacer(1, 14))

    # =========================================================================
    # 5. DỰ TOÁN NGÂN SÁCH (BUDGET BREAKDOWN)
    # =========================================================================
    story.append(Paragraph("5. DỰ TOÁN & PHÂN BỔ NGÂN SÁCH CHI TIẾT", style_h1))

    budget_data = [
        [
            Paragraph("Khoản mục Chi phí", style_table_header),
            Paragraph("Đơn vị / Cơ sở tính", style_table_header),
            Paragraph("Số tiền (VNĐ)", style_table_header),
            Paragraph("Tỷ trọng", style_table_header),
        ],
        [
            Paragraph("1. Nhân sự kỹ thuật cốt lõi (Core Engineering Team)", style_table_cell),
            Paragraph("6 nhân sự x 2 tháng", style_table_cell),
            Paragraph("420.000.000", style_table_cell),
            Paragraph("64.6%", style_table_cell),
        ],
        [
            Paragraph("2. Hạ tầng Cloud & Cơ sở dữ liệu MongoDB Atlas", style_table_cell),
            Paragraph("Cụm M20 Dedicated Cluster + Backup", style_table_cell),
            Paragraph("80.000.000", style_table_cell),
            Paragraph("12.3%", style_table_cell),
        ],
        [
            Paragraph("3. Hạn ngạch LLM API (Google Gemini Enterprise)", style_table_cell),
            Paragraph("10 triệu tokens trích xuất & suy luận", style_table_cell),
            Paragraph("90.000.000", style_table_cell),
            Paragraph("13.8%", style_table_cell),
        ],
        [
            Paragraph("4. Chi phí Đào tạo, UAT & Dự phòng rủi ro", style_table_cell),
            Paragraph("10% tổng dự toán", style_table_cell),
            Paragraph("60.000.000", style_table_cell),
            Paragraph("9.3%", style_table_cell),
        ],
        [
            Paragraph("<b>TỔNG CỘNG NGÂN SÁCH ĐƯỢC DUYỆT</b>", style_table_cell),
            Paragraph("<b>Tất cả các hạng mục</b>", style_table_cell),
            Paragraph("<b>650.000.000 VNĐ</b>", style_table_cell),
            Paragraph("<b>100.0%</b>", style_table_cell),
        ],
    ]

    t_budget = Table(budget_data, colWidths=[185, 150, 110, 70])
    t_budget.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (2, 1), (3, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BG_LIGHT]),
    ]))
    story.append(t_budget)
    story.append(Spacer(1, 16))

    # =========================================================================
    # 6. PHÊ DUYỆT & KÝ TÊN (SIGN-OFF SECTION)
    # =========================================================================
    sign_block = []
    sign_block.append(Paragraph("6. XÁC NHẬN & PHÊ DUYỆT KẾ HOẠCH", style_h1))
    sign_block.append(Spacer(1, 6))

    sign_data = [
        [
            Paragraph("<b>ĐẠI DIỆN CHỦ ĐẦU TƯ</b><br/><i>(Ký và ghi rõ họ tên)</i>", style_table_cell),
            Paragraph("<b>PROJECT LEAD</b><br/><i>(Ký và ghi rõ họ tên)</i>", style_table_cell),
            Paragraph("<b>ĐẠI DIỆN KHÁCH HÀNG (COWI)</b><br/><i>(Ký và ghi rõ họ tên)</i>", style_table_cell),
        ],
        [
            Paragraph("<br/><br/><br/><b>Ban Giám Đốc HiLark</b>", style_table_cell),
            Paragraph("<br/><br/><br/><b>Nguyễn Hoài Nam</b>", style_table_cell),
            Paragraph("<br/><br/><br/><b>Đại diện Cowi Tech Group</b>", style_table_cell),
        ],
    ]

    t_sign = Table(sign_data, colWidths=[170, 175, 170])
    t_sign.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    sign_block.append(t_sign)

    story.append(KeepTogether(sign_block))

    # Build PDF với canvas đánh số trang 2-pass
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"✔ Đã xuất tài liệu PDF thành công: {output_path}")


if __name__ == "__main__":
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    output_pdf = os.path.join(tests_dir, "du_an_mau_hilark.pdf")
    create_project_pdf(output_pdf)
