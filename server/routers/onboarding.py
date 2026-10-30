"""
HiLark - Onboarding Screen Guide Router
=======================================
Vị trí: server/routers/onboarding.py

Cung cấp:
  1. GET  /onboarding/wizard       : Giao diện Stepper Wizard 4 bước bằng HTML/CSS/JS (Dark Mode).
  2. POST /onboarding/api/test-key : Endpoint AJAX kiểm tra tính sống còn và latency của Gemini Key.
  3. POST /onboarding/api/save     : Lưu toàn bộ cấu hình vào MongoDB collection 'user_settings'.
  4. GET  /onboarding/api/settings/{open_id} : Lấy cấu hình hiện tại để điền sẵn vào Wizard.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from core.config import settings
from services.user_settings_service import user_settings_service

logger = logging.getLogger("hilark.router.onboarding")
router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class TestKeyRequest(BaseModel):
    api_key: str = Field(..., description="Gemini API Key cần kiểm tra")


class SaveSettingsRequest(BaseModel):
    open_id: str = Field(..., description="Lark Open ID của người dùng (ou_xxx)")
    user_name: Optional[str] = Field(default=None, description="Tên người dùng")
    is_byok_enabled: bool = Field(default=False, description="Kích hoạt BYOK hay không")
    raw_gemini_key: Optional[str] = Field(default=None, description="Khóa API mới (nếu có)")
    digest_schedule_time: str = Field(default="18:00", description="Giờ nhận Daily Digest")
    hitl_mode_enabled: bool = Field(default=True, description="Bật chế độ duyệt an toàn HITL")


@router.post("/api/test-key")
async def test_key_endpoint(req: TestKeyRequest):
    """Kiểm tra trực tiếp độ sống và độ trễ của Gemini API Key qua AJAX."""
    ok, msg, latency = await user_settings_service.test_gemini_key(req.api_key)
    return {
        "success": ok,
        "message": msg,
        "latency_ms": latency,
    }


@router.post("/api/save")
async def save_settings_endpoint(req: SaveSettingsRequest):
    """Lưu cấu hình sau khi người dùng hoàn thành 4 bước trên Screen Guide."""
    try:
        record = await user_settings_service.save_user_settings(
            open_id=req.open_id,
            is_byok_enabled=req.is_byok_enabled,
            raw_gemini_key=req.raw_gemini_key,
            digest_schedule_time=req.digest_schedule_time,
            hitl_mode_enabled=req.hitl_mode_enabled,
            user_name=req.user_name,
        )
        return {
            "success": True,
            "message": "Đã lưu cấu hình trợ lý thành công!",
            "data": record.to_dict(),
        }
    except Exception as e:
        logger.error(f"Lỗi khi lưu cấu hình onboarding: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/settings/{open_id}")
async def get_settings_endpoint(open_id: str):
    """Lấy thông tin cấu hình hiện hành để hiển thị trên Wizard."""
    record = await user_settings_service.get_user_settings(open_id)
    if not record:
        return {
            "success": True,
            "data": {
                "open_id": open_id,
                "is_byok_enabled": False,
                "masked_gemini_api_key": "",
                "digest_schedule_time": "18:00",
                "hitl_mode_enabled": True,
            },
        }
    return {
        "success": True,
        "data": record.to_dict(),
    }


@router.get("/wizard", response_class=HTMLResponse)
async def onboarding_wizard_page(
    request: Request,
    open_id: Optional[str] = Query(None, description="Lark Open ID của người dùng"),
    user_name: Optional[str] = Query(None, description="Tên người dùng"),
):
    """Render giao diện Screen Guide Wizard 4 bước mở trong Lark Applink Webview Modal."""
    effective_open_id = open_id or settings.LARK_USER_OPEN_ID or "ou_user_default"
    effective_user_name = user_name or settings.LARK_USER_NAME or "Lãnh đạo"

    base_url = str(request.base_url).rstrip("/")
    oauth_url = f"{base_url}/auth/lark/login?redirect=true"

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HiLark — Hướng Dẫn Cài Đặt Trợ Lý AI (Screen Guide)</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #6366f1;
            --primary-hover: #4f46e5;
            --bg-dark: #090d16;
            --card-bg: rgba(19, 26, 43, 0.85);
            --border: rgba(255, 255, 255, 0.08);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --success: #22c55e;
            --danger: #ef4444;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: radial-gradient(circle at top, #1e1b4b 0%, #090d16 100%);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            overflow-x: hidden;
        }}
        .wizard-container {{
            background: var(--card-bg);
            backdrop-filter: blur(24px);
            border: 1px solid var(--border);
            border-radius: 24px;
            width: 100%;
            max-width: 540px;
            box-shadow: 0 30px 60px -15px rgba(0, 0, 0, 0.7);
            position: relative;
            overflow: hidden;
        }}
        /* Stepper Header */
        .stepper-header {{
            padding: 24px 32px 16px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .step-dots {{
            display: flex;
            gap: 8px;
        }}
        .dot {{
            width: 32px;
            height: 6px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.15);
            transition: all 0.3s ease;
        }}
        .dot.active {{
            background: var(--primary);
            box-shadow: 0 0 12px rgba(99, 102, 241, 0.6);
            width: 48px;
        }}
        .dot.completed {{
            background: var(--success);
        }}
        .step-label {{
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
        }}

        /* Carousel Slides */
        .slider-wrapper {{
            position: relative;
            width: 100%;
            min-height: 420px;
        }}
        .slide {{
            display: none;
            padding: 32px;
            animation: fadeIn 0.35s ease forwards;
        }}
        .slide.active {{
            display: block;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateX(20px); }}
            to {{ opacity: 1; transform: translateX(0); }}
        }}

        h2 {{
            font-size: 22px;
            font-weight: 800;
            color: #fff;
            margin-bottom: 8px;
            letter-spacing: -0.02em;
        }}
        p.desc {{
            color: var(--text-muted);
            font-size: 14px;
            line-height: 1.6;
            margin-bottom: 24px;
        }}

        /* Feature Cards (Screen 1) */
        .feature-box {{
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .feat-icon {{
            font-size: 24px;
            width: 44px;
            height: 44px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(99, 102, 241, 0.15);
            border: 1px solid rgba(99, 102, 241, 0.3);
            flex-shrink: 0;
        }}
        .feat-title {{ font-size: 14px; font-weight: 700; color: #fff; margin-bottom: 2px; }}
        .feat-desc {{ font-size: 12px; color: var(--text-muted); line-height: 1.4; }}

        /* Radio Options & Inputs (Screen 2 & 3) */
        .option-card {{
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 12px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: flex-start;
            gap: 12px;
            background: rgba(15, 23, 42, 0.4);
        }}
        .option-card:hover {{
            background: rgba(99, 102, 241, 0.08);
            border-color: rgba(99, 102, 241, 0.4);
        }}
        .option-card.selected {{
            background: rgba(99, 102, 241, 0.12);
            border-color: var(--primary);
            box-shadow: 0 0 15px rgba(99, 102, 241, 0.2);
        }}
        .radio-circle {{
            width: 18px;
            height: 18px;
            border-radius: 50%;
            border: 2px solid rgba(255, 255, 255, 0.3);
            margin-top: 2px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }}
        .option-card.selected .radio-circle {{
            border-color: var(--primary);
        }}
        .option-card.selected .radio-circle::after {{
            content: '';
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--primary);
        }}
        .input-group {{
            margin-top: 16px;
        }}
        .input-wrapper {{
            display: flex;
            background: #0f172a;
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            margin-top: 8px;
        }}
        .key-input {{
            flex: 1;
            background: transparent;
            border: none;
            padding: 14px;
            color: #38bdf8;
            font-family: monospace;
            font-size: 13px;
            outline: none;
        }}
        .test-btn {{
            background: rgba(99, 102, 241, 0.2);
            color: #818cf8;
            border: none;
            padding: 0 16px;
            font-weight: 600;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
            border-left: 1px solid var(--border);
        }}
        .test-btn:hover {{ background: var(--primary); color: #fff; }}
        .feedback-badge {{
            display: inline-block;
            font-size: 12px;
            padding: 6px 12px;
            border-radius: 8px;
            margin-top: 8px;
            font-weight: 600;
        }}
        .badge-success {{ background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }}
        .badge-danger {{ background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }}

        /* Select styling */
        select.custom-select {{
            width: 100%;
            background: #0f172a;
            border: 1px solid var(--border);
            color: #fff;
            padding: 14px;
            border-radius: 12px;
            font-size: 14px;
            outline: none;
            margin-top: 8px;
        }}

        /* Buttons Footer */
        .wizard-footer {{
            padding: 20px 32px 28px;
            border-top: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .btn {{
            padding: 12px 24px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
            border: none;
            text-decoration: none;
        }}
        .btn-prev {{
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-muted);
        }}
        .btn-prev:hover {{ background: rgba(255, 255, 255, 0.15); color: #fff; }}
        .btn-next {{
            background: linear-gradient(135deg, var(--primary) 0%, #7c3aed 100%);
            color: #fff;
            box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
        }}
        .btn-next:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(99, 102, 241, 0.5);
        }}
    </style>
</head>
<body>
    <div class="wizard-container">
        <!-- Stepper Bar -->
        <div class="stepper-header">
            <span class="step-label" id="stepIndicator">BƯỚC 1 / 4: GIỚI THIỆU</span>
            <div class="step-dots">
                <div class="dot active" id="dot1"></div>
                <div class="dot" id="dot2"></div>
                <div class="dot" id="dot3"></div>
                <div class="dot" id="dot4"></div>
            </div>
        </div>

        <div class="slider-wrapper">
            <!-- SLIDE 1: WELCOME & OVERVIEW -->
            <div class="slide active" id="slide1">
                <h2>Chào mừng Sếp {effective_user_name}! 🚀</h2>
                <p class="desc">Trợ lý AI HiLark đã được nạp thành công vào workspace. Dưới đây là 3 khả năng cốt lõi phục vụ điều hành:</p>
                
                <div class="feature-box">
                    <div class="feat-icon">🧠</div>
                    <div>
                        <div class="feat-title">Phân Loại JEV 0ms</div>
                        <div class="feat-desc">Lọc tin rác tức thì, tự động bóc tách tiến độ, quyết định và cam kết vào bộ nhớ.</div>
                    </div>
                </div>
                <div class="feature-box">
                    <div class="feat-icon">🛡️</div>
                    <div>
                        <div class="feat-title">Bảo Mật Vùng Cấm 0% Rò Rỉ</div>
                        <div class="feat-desc">Chặn tự động số liệu nhạy cảm (ngân sách, lương bổng), chuyển thành bản nháp gửi riêng Sếp duyệt.</div>
                    </div>
                </div>
                <div class="feature-box">
                    <div class="feat-icon">📊</div>
                    <div>
                        <div class="feat-title">Báo Cáo Điều Hành Cuối Ngày</div>
                        <div class="feat-desc">Tự động tổng hợp nhật ký ngày (Daily Digest) kèm nguồn tin và duyệt 1-chạm.</div>
                    </div>
                </div>
            </div>

            <!-- SLIDE 2: AI ENGINE & BYOK -->
            <div class="slide" id="slide2">
                <h2>Cấu Hình Bộ Não AI &amp; API Key 🔑</h2>
                <p class="desc">Chọn nguồn hạn mức AI phục vụ trả lời câu hỏi và tổng hợp tri thức:</p>

                <div class="option-card selected" id="optSystemKey" onclick="selectApiKeyMode(false)">
                    <div class="radio-circle"></div>
                    <div>
                        <div class="feat-title">Dùng Hạn Mức Mặc Định Của Hệ Thống (Khuyên dùng)</div>
                        <div class="feat-desc">Miễn phí, sử dụng cụm Gemini của công ty. Không cần cài đặt thêm.</div>
                    </div>
                </div>

                <div class="option-card" id="optByok" onclick="selectApiKeyMode(true)">
                    <div class="radio-circle"></div>
                    <div>
                        <div class="feat-title">Tự Mang API Key Riêng (BYOK - Google Gemini)</div>
                        <div class="feat-desc">Sử dụng tài khoản Google AI Studio riêng của bạn để không lo giới hạn quota.</div>
                    </div>
                </div>

                <div class="input-group" id="byokInputGroup" style="display: none;">
                    <label style="font-size: 12px; color: var(--text-muted); font-weight: 600;">DÁN GEMINI API KEY CỦA BẠN:</label>
                    <div class="input-wrapper">
                        <input type="password" id="geminiKeyInput" class="key-input" placeholder="AIzaSyBxxxxxxxxxxxxxxxxxxxxxxxxxxxx">
                        <button type="button" class="test-btn" onclick="testKeyLive()">⚡ Kiểm tra key</button>
                    </div>
                    <div id="testFeedback"></div>
                </div>
            </div>

            <!-- SLIDE 3: DAILY DIGEST & HITL -->
            <div class="slide" id="slide3">
                <h2>Lịch Nhận Báo Cáo &amp; Kiểm Duyệt ⏰</h2>
                <p class="desc">Thiết lập thời gian nhận bản tóm tắt Master Daily Digest gửi riêng vào tin nhắn của bạn:</p>

                <label style="font-size: 13px; font-weight: 700; color: #fff;">Khung giờ nhận báo cáo tổng hợp:</label>
                <select id="digestTimeSelect" class="custom-select">
                    <option value="18:00" selected>18:00 (Cuối giờ làm việc - Khuyên dùng)</option>
                    <option value="17:30">17:30 (Trước giờ tan ca)</option>
                    <option value="21:00">21:00 (Buổi tối)</option>
                    <option value="23:00">23:00 (Tổng kết đêm muộn)</option>
                </select>

                <div style="margin-top: 24px; padding: 16px; background: rgba(15, 23, 42, 0.5); border: 1px solid var(--border); border-radius: 14px;">
                    <label style="display: flex; align-items: center; gap: 12px; cursor: pointer;">
                        <input type="checkbox" id="hitlCheckbox" checked style="width: 18px; height: 18px; accent-color: var(--primary);">
                        <div>
                            <div style="font-size: 14px; font-weight: 700; color: #fff;">Bật chế độ kiểm duyệt an toàn (Strict HITL)</div>
                            <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">Mọi câu trả lời nhạy cảm và báo cáo ngày phải được bạn duyệt trước khi gửi công khai.</div>
                        </div>
                    </label>
                </div>
            </div>

            <!-- SLIDE 4: OAUTH & COMPLETE -->
            <div class="slide" id="slide4">
                <h2>Ủy Quyền Đại Diện &amp; Hoàn Tất 🚀</h2>
                <p class="desc">Bước cuối cùng để Bot có thể thay mặt bạn trả lời câu hỏi và đọc tài liệu dự án:</p>

                <div style="text-align: center; padding: 24px 16px; background: rgba(99, 102, 241, 0.08); border: 1px solid rgba(99, 102, 241, 0.2); border-radius: 16px; margin-bottom: 20px;">
                    <div style="font-size: 32px; margin-bottom: 12px;">🔗</div>
                    <div style="font-weight: 700; font-size: 15px; color: #fff; margin-bottom: 6px;">Ủy quyền Lark OAuth 2.0 (1 Lần Duy Nhất)</div>
                    <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 16px;">Tự động gia hạn vĩnh viễn trong MongoDB, an toàn bảo mật.</div>
                    <a href="{oauth_url}" target="_blank" class="btn" style="background: rgba(99, 102, 241, 0.25); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.4); display: inline-block;">
                        👉 Bấm vào đây để Ủy quyền Lark
                    </a>
                </div>

                <div id="saveFeedback" style="text-align: center; margin-top: 10px;"></div>
            </div>
        </div>

        <!-- Footer Navigation -->
        <div class="wizard-footer">
            <button type="button" class="btn btn-prev" id="btnPrev" onclick="navigateStep(-1)" style="display: none;">← Quay lại</button>
            <div style="flex: 1;"></div>
            <button type="button" class="btn btn-next" id="btnNext" onclick="navigateStep(1)">Bắt đầu thiết lập →</button>
        </div>
    </div>

    <script>
        let currentStep = 1;
        const totalSteps = 4;
        let isByok = false;
        const userOpenId = "{effective_open_id}";
        const userName = "{effective_user_name}";

        const stepTitles = [
            "BƯỚC 1 / 4: GIỚI THIỆU",
            "BƯỚC 2 / 4: CẤU HÌNH AI & BYOK",
            "BƯỚC 3 / 4: DAILY DIGEST & HITL",
            "BƯỚC 4 / 4: HOÀN TẤT & LƯU"
        ];

        function navigateStep(direction) {{
            if (direction === 1 && currentStep === totalSteps) {{
                // Hoàn tất và lưu
                saveFinalSettings();
                return;
            }}

            currentStep += direction;
            if (currentStep < 1) currentStep = 1;
            if (currentStep > totalSteps) currentStep = totalSteps;

            updateUI();
        }}

        function updateUI() {{
            document.getElementById("stepIndicator").innerText = stepTitles[currentStep - 1];

            for (let i = 1; i <= totalSteps; i++) {{
                const slide = document.getElementById(`slide${{i}}`);
                const dot = document.getElementById(`dot${{i}}`);
                if (i === currentStep) {{
                    slide.classList.add("active");
                    dot.classList.add("active");
                    dot.classList.remove("completed");
                }} else if (i < currentStep) {{
                    slide.classList.remove("active");
                    dot.classList.remove("active");
                    dot.classList.add("completed");
                }} else {{
                    slide.classList.remove("active");
                    dot.classList.remove("active");
                    dot.classList.remove("completed");
                }}
            }}

            const btnPrev = document.getElementById("btnPrev");
            const btnNext = document.getElementById("btnNext");

            btnPrev.style.display = currentStep > 1 ? "block" : "none";

            if (currentStep === 1) {{
                btnNext.innerText = "Bắt đầu thiết lập →";
            }} else if (currentStep === totalSteps) {{
                btnNext.innerText = "💾 Hoàn tất & Kích hoạt";
            }} else {{
                btnNext.innerText = "Tiếp tục →";
            }}
        }}

        function selectApiKeyMode(enableByok) {{
            isByok = enableByok;
            const optSys = document.getElementById("optSystemKey");
            const optByok = document.getElementById("optByok");
            const inputGroup = document.getElementById("byokInputGroup");

            if (enableByok) {{
                optSys.classList.remove("selected");
                optByok.classList.add("selected");
                inputGroup.style.display = "block";
            }} else {{
                optSys.classList.add("selected");
                optByok.classList.remove("selected");
                inputGroup.style.display = "none";
            }}
        }}

        async function testKeyLive() {{
            const keyInput = document.getElementById("geminiKeyInput").value.trim();
            const feedback = document.getElementById("testFeedback");
            if (!keyInput) {{
                feedback.innerHTML = '<span class="feedback-badge badge-danger">Vui lòng nhập API Key trước khi kiểm tra.</span>';
                return;
            }}

            feedback.innerHTML = '<span class="feedback-badge" style="background: rgba(255,255,255,0.1); color: #fff;">Đang ping tới Google Gemini API...</span>';

            try {{
                const res = await fetch("/onboarding/api/test-key", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ api_key: keyInput }})
                }});
                const data = await res.json();
                if (data.success) {{
                    feedback.innerHTML = `<span class="feedback-badge badge-success">✔ ${{data.message}} (Độ trễ: ${{data.latency_ms}}ms)</span>`;
                }} else {{
                    feedback.innerHTML = `<span class="feedback-badge badge-danger">❌ ${{data.message}}</span>`;
                }}
            }} catch (err) {{
                feedback.innerHTML = `<span class="feedback-badge badge-danger">Lỗi kết nối kiểm tra: ${{err.message}}</span>`;
            }}
        }}

        async function saveFinalSettings() {{
            const btnNext = document.getElementById("btnNext");
            const feedback = document.getElementById("saveFeedback");
            btnNext.innerText = "Đang lưu cấu hình...";
            btnNext.disabled = true;

            const payload = {{
                open_id: userOpenId,
                user_name: userName,
                is_byok_enabled: isByok,
                raw_gemini_key: isByok ? document.getElementById("geminiKeyInput").value.trim() : null,
                digest_schedule_time: document.getElementById("digestTimeSelect").value,
                hitl_mode_enabled: document.getElementById("hitlCheckbox").checked
            }};

            try {{
                const res = await fetch("/onboarding/api/save", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify(payload)
                }});
                const result = await res.json();
                if (result.success) {{
                    feedback.innerHTML = '<div style="color: #4ade80; font-weight: 700; font-size: 16px; margin-top: 12px;">🎉 CÀI ĐẶT THÀNH CÔNG!<br><span style="font-size: 13px; font-weight: 400; color: #94a3b8;">Cửa sổ sẽ tự đóng lại sau 2 giây. Bạn có thể bắt đầu chat ngay với Bot.</span></div>';
                    setTimeout(() => {{
                        window.close();
                    }}, 2200);
                }} else {{
                    feedback.innerHTML = `<div style="color: #f87171; font-size: 13px;">❌ ${{result.message || 'Lỗi khi lưu'}}</div>`;
                    btnNext.innerText = "Thử lại";
                    btnNext.disabled = false;
                }}
            }} catch (e) {{
                feedback.innerHTML = `<div style="color: #f87171; font-size: 13px;">❌ Lỗi hệ thống: ${{e.message}}</div>`;
                btnNext.innerText = "Thử lại";
                btnNext.disabled = false;
            }}
        }}

        // Tự động load cấu hình cũ nếu có
        window.addEventListener("DOMContentLoaded", async () => {{
            try {{
                const res = await fetch(`/onboarding/api/settings/${{userOpenId}}`);
                const json = await res.json();
                if (json.success && json.data) {{
                    const d = json.data;
                    if (d.digest_schedule_time) {{
                        document.getElementById("digestTimeSelect").value = d.digest_schedule_time;
                    }}
                    document.getElementById("hitlCheckbox").checked = d.hitl_mode_enabled !== false;
                    if (d.is_byok_enabled) {{
                        selectApiKeyMode(true);
                        if (d.masked_gemini_api_key) {{
                            document.getElementById("geminiKeyInput").placeholder = d.masked_gemini_api_key;
                        }}
                    }}
                }}
            }} catch(e) {{}}
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

