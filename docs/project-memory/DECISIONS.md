# Decision Index

> Chỉ mục ngắn trong repo. Hồ sơ đầy đủ có thể nằm trong Notion. Không tạo ID hoặc URL giả.

| ID | Decision | Status | Impact | Date | Notion record | Code / commit |
|---|---|---|---|---|---|---|
| EDL-0002 | [Chiến lược Phân tầng Tri thức & Đồng bộ Đa tài liệu](https://app.notion.com/p/EDL-0002-Chi-n-l-c-Ph-n-t-ng-Tri-th-c-ng-b-a-t-i-li-u-402590f7e19e81ef82bbeb091ece965f) | Approved | High | 2026-10-23 | [Notion Page](https://app.notion.com/p/EDL-0002-Chi-n-l-c-Ph-n-t-ng-Tri-th-c-ng-b-a-t-i-li-u-402590f7e19e81ef82bbeb091ece965f) | `server/models/chat_scope.py`, `server/utils/context_composer.py` |
| EDL-0003 | [JEV Piggyback Routing cho Phân tầng Tri thức](https://app.notion.com/p/EDL-0003-JEV-Piggyback-Routing-cho-Ph-n-t-ng-Tri-th-c-Project-KB-vs-Global-Wiki-402590f7e19e8179bc26ed7248bb725b) | Approved | High | 2026-10-23 | [Notion Page](https://app.notion.com/p/EDL-0003-JEV-Piggyback-Routing-cho-Ph-n-t-ng-Tri-th-c-Project-KB-vs-Global-Wiki-402590f7e19e8179bc26ed7248bb725b) | `server/services/jev.py`, `server/services/chat_service.py` |
| EDL-0004 | [Tận dụng WeKnora Document Summary làm Macro-Context](https://app.notion.com/p/EDL-0004-T-n-d-ng-WeKnora-Document-Summary-l-m-Macro-Context-cho-Auto-Manifest-ContextComposer-402590f7e19e810093e5c38fe1e74da5) | Approved | High | 2026-10-23 | [Notion Page](https://app.notion.com/p/EDL-0004-T-n-d-ng-WeKnora-Document-Summary-l-m-Macro-Context-cho-Auto-Manifest-ContextComposer-402590f7e19e810093e5c38fe1e74da5) | `server/services/scope_service.py`, `server/utils/context_composer.py` |
| EDL-0005 | [Pipeline Đồng bộ Policy Tự động (Lark Base Thin Bridge & WeKnora Data Source)](https://app.notion.com/p/EDL-0005-Pipeline-ng-b-Policy-T-ng-Lark-Base-Thin-Bridge-WeKnora-Data-Source-403590f7e19e81258ed3e2b2eb444f9c) | Approved | High | 2026-10-24 | [Notion Page](https://app.notion.com/p/EDL-0005-Pipeline-ng-b-Policy-T-ng-Lark-Base-Thin-Bridge-WeKnora-Data-Source-403590f7e19e81258ed3e2b2eb444f9c) | `server/services/policy_sync_service.py`, `server/routers/policy.py`, `server/services/weknora.py` |
| EDL-0006 | [Tự động Làm mới Lark User Token (OAuth2 Single-Use Refresh Token Rotation & MongoDB Storage)](https://app.notion.com/p/EDL-0006-T-ng-L-m-m-i-Lark-User-Token-OAuth2-Single-Use-Refresh-Token-Rotation-MongoDB-Stora-403590f7e19e81ec908fc1f4527802fe) | Approved | High | 2026-10-24 | [Notion Page](https://app.notion.com/p/EDL-0006-T-ng-L-m-m-i-Lark-User-Token-OAuth2-Single-Use-Refresh-Token-Rotation-MongoDB-Stora-403590f7e19e81ec908fc1f4527802fe) | `server/services/token_service.py`, `server/routers/auth.py`, `server/services/larkServices/lark_client.py` |
| EDL-0007 | [Định tuyến RAG Đa kho & Miễn trừ Nhãn cấm Dự án cho Văn bản Chính sách Công ty](https://app.notion.com/p/EDL-0007-nh-tuy-n-RAG-a-kho-Mi-n-tr-Nh-n-c-m-D-n-cho-V-n-b-n-Ch-nh-s-ch-C-ng-ty-403590f7e19e81759524ffcc0fc15288) | Approved | High | 2026-10-24 | [Notion Page](https://app.notion.com/p/EDL-0007-nh-tuy-n-RAG-a-kho-Mi-n-tr-Nh-n-c-m-D-n-cho-V-n-b-n-Ch-nh-s-ch-C-ng-ty-403590f7e19e81759524ffcc0fc15288) | `server/services/chat_service.py`, `server/tests/01/test_policy_qa.py` |
| EDL-0008 | [Kiến trúc Contextual Claim Gate: Kiểm soát Nạp Claims Động và Chống Ô nhiễm Ngữ cảnh RAG](https://app.notion.com/p/EDL-0008-Ki-n-tr-c-Contextual-Claim-Gate-Ki-m-so-t-N-p-Claims-ng-v-Ch-ng-nhi-m-Ng-c-nh-RAG-403590f7e19e81d79957cd187c3df8fa) | Approved | High | 2026-10-24 | [Notion Page](https://app.notion.com/p/EDL-0008-Ki-n-tr-c-Contextual-Claim-Gate-Ki-m-so-t-N-p-Claims-ng-v-Ch-ng-nhi-m-Ng-c-nh-RAG-403590f7e19e81d79957cd187c3df8fa) | `server/utils/context_composer.py`, `server/services/chat_service.py`, `server/utils/llm_extractor.py` |
| EDL-0009 | [Đánh Giá Chất Lượng Codebase, Phân Loại Code Dirty và Chiến Lược Giải Quyết Nợ Kỹ Thuật](https://app.notion.com/p/EDL-0009-nh-Gi-Ch-t-L-ng-Codebase-Ph-n-Lo-i-Code-Dirty-v-Chi-n-L-c-Gi-i-Quy-t-N-K-Thu-t-403590f7e19e81a3b443e08deef4e925) | Approved | High | 2026-10-24 | [Notion Page](https://app.notion.com/p/EDL-0009-nh-Gi-Ch-t-L-ng-Codebase-Ph-n-Lo-i-Code-Dirty-v-Chi-n-L-c-Gi-i-Quy-t-N-K-Thu-t-403590f7e19e81a3b443e08deef4e925) | `docs/project-memory/TECHNICAL_DEBT.md`, `server/database/db.py`, `server/services/` |
| EDL-0010 | [Kiến trúc Tầng Phân Giải Tài Liệu Đa Phương Tiện (AnyDoc gRPC & Lark OpenAPI) & Cơ Chế Xử Lý Xung Đột Tri Thức](https://app.notion.com/p/EDL-0010-Ki-n-tr-c-T-ng-Ph-n-Gi-i-T-i-Li-u-a-Ph-ng-Ti-n-AnyDoc-gRPC-Lark-OpenAPI-Tr-ch-Xu--403590f7e19e811a9a02cd8ddff7c38b) | Approved | High | 2026-10-24 | [Notion Page](https://app.notion.com/p/EDL-0010-Ki-n-tr-c-T-ng-Ph-n-Gi-i-T-i-Li-u-a-Ph-ng-Ti-n-AnyDoc-gRPC-Lark-OpenAPI-Tr-ch-Xu--403590f7e19e811a9a02cd8ddff7c38b) | `server/utils/context_composer.py`, `server/services/doc_parser_service.py`, `WeKnora/docker-compose.yml` |
| EDL-0011 | [Kiến trúc Phê duyệt Đa tầng (3-Tier Decision Governance) & Cách ly Tuyệt đối Phạm vi Claims](https://app.notion.com/p/EDL-0011-Ki-n-tr-c-Ph-duy-t-a-t-ng-3-Tier-Decision-Governance-C-ch-ly-Tuy-t-i-Ph-m-vi-Claim-406590f7e19e81358dbbd486ccf9e518) | Approved | High | 2026-10-27 | [Notion Page](https://app.notion.com/p/EDL-0011-Ki-n-tr-c-Ph-duy-t-a-t-ng-3-Tier-Decision-Governance-C-ch-ly-Tuy-t-i-Ph-m-vi-Claim-406590f7e19e81358dbbd486ccf9e518) | `server/services/workflows/chat_workflow.py`, `server/services/knowledge/context_composer.py`, `server/services/ai/jev_classifier.py`, `server/services/lark/handlers/member_message_handler.py`, `server/services/lark/dispatcher.py`, `server/services/workflows/digest_workflow.py`, `server/database/db.py` |
| EDL-0012 | [Giao diện Thẻ tương tác (Lark Interactive Card V2), AI Rewrite và Cơ chế Phê duyệt Điều hành Thời gian thực](https://app.notion.com/p/EDL-0012-Giao-di-n-Th-t-ng-t-c-Lark-Interactive-Card-V2-AI-Rewrite-v-C-ch-Ph-duy-t-i-u-h--406590f7e19e81c08631ec5621d1ed24) | Approved | High | 2026-10-27 | [Notion Page](https://app.notion.com/p/EDL-0012-Giao-di-n-Th-t-ng-t-c-Lark-Interactive-Card-V2-AI-Rewrite-v-C-ch-Ph-duy-t-i-u-h--406590f7e19e81c08631ec5621d1ed24) | `server/services/lark/card_builder.py`, `server/services/ai/draft_rewriter.py`, `server/services/workflows/claim_workflow.py`, `server/services/claim_service.py`, `server/services/lark/handlers/card_action_handler.py`, `server/services/lark/messenger.py`, `server/services/workflows/chat_workflow.py`, `server/services/workflows/digest_workflow.py`, `server/services/lark/handlers/owner_command_handler.py`, `server/routers/lark.py` |
| EDL-0013 | [Trích Xuất Tài Liệu Ảnh (Gemini Vision OCR), Gom Nhóm Thông Tin Đề Xuất & Duyệt Báo Cáo Ngày Một Chạm](https://app.notion.com/p/EDL-0013-Tr-ch-Xu-t-T-i-Li-u-nh-Gemini-Vision-OCR-Gom-Nh-m-Th-ng-Tin-Xu-t-Duy-t-B-o-C-o-Ng-406590f7e19e81fb92c8d8e75a1a8b4f) | Approved | High | 2026-10-27 | [Notion Page](https://app.notion.com/p/EDL-0013-Tr-ch-Xu-t-T-i-Li-u-nh-Gemini-Vision-OCR-Gom-Nh-m-Th-ng-Tin-Xu-t-Duy-t-B-o-C-o-Ng-406590f7e19e81fb92c8d8e75a1a8b4f) | `server/services/knowledge/doc_parser.py`, `server/services/ai/gemini_client.py`, `server/services/lark/card_builder.py`, `server/services/lark/handlers/card_action_handler.py`, `server/services/lark/handlers/owner_command_handler.py`, `server/services/workflows/digest_workflow.py`, `server/services/workflows/claim_workflow.py`, `server/database/db.py` |
| EDL-0014 | Kiến trúc Decorator Đo Lường Chi Phí LLM & JEV (Cost Telemetry & Tracking Decorators) | Approved | Medium | 2026-10-27 | Local Record | `server/decorators/`, `server/services/ai/gemini_client.py`, `server/services/ai/jev_classifier.py`, `server/database/indexes.py` |
| EDL-0015 | Kiến trúc Xử lý Thu Hồi Tin Nhắn (Message Recall Architecture & 4-Tier Cascade Sync) | Approved | High | 2026-10-28 | Local Record | `server/services/lark/handlers/recall_handler.py`, `server/services/lark/messenger.py`, `server/services/lark/dispatcher.py`, `server/database/db.py`, `server/services/workflows/digest_workflow.py` |
| EDL-0016 | Kiến trúc Nạp Tài Liệu Thư Mục Đám Mây Lark Drive (Folder Ingestion & Recursive Traversal Pipeline) | Approved | High | 2026-10-29 | Local Record | `server/services/lark/client.py`, `server/services/knowledge/doc_parser.py`, `server/services/knowledge/chat_scopes.py`, `server/services/lark/handlers/document_handler.py`, `server/routers/scope.py`, `server/tests/final_test/test_folder_doc_ingestion.py` |
| EDL-0017 | [Kiến trúc Hybrid BYOK (AES-256 Fernet), Lark Modal Webview Screen Guide & Cụm Triển khai Sản xuất Zero-Ingress](https://app.notion.com/p/EDL-0017-Ki-n-tr-c-Hybrid-BYOK-AES-256-Fernet-Lark-Modal-Webview-Screen-Guide-C-m-Tri-n-khai-S-409590f7e19e815cb181fad3e5a8162a) | Partly Superseded by EDL-0075 | High | 2026-10-30 | [Notion Page](https://app.notion.com/p/EDL-0017-Ki-n-tr-c-Hybrid-BYOK-AES-256-Fernet-Lark-Modal-Webview-Screen-Guide-C-m-Tri-n-khai-S-409590f7e19e815cb181fad3e5a8162a) | `server/services/user_settings_service.py`, `server/routers/onboarding.py`, `server/services/lark/card_builder.py`, `server/Dockerfile`, `docker-compose.prod.yml`, `deploy.sh`, `docs/DEPLOYMENT_GUIDE.md` |
| EDL-0018 | [Tự động Khởi tạo 100% Lark Base Doanh nghiệp (Zero-Touch Auto-Provisioning via Lark OpenAPI) & Phân giải Cấu hình Động](https://app.notion.com/p/EDL-0018-T-ng-Kh-i-t-o-100-Lark-Base-Doanh-nghi-p-Zero-Touch-Auto-Provisioning-via-Lark-OpenAP-409590f7e19e8174ab83cbe2df6087aa) | Approved | High | 2026-10-30 | [Notion Page](https://app.notion.com/p/EDL-0018-T-ng-Kh-i-t-o-100-Lark-Base-Doanh-nghi-p-Zero-Touch-Auto-Provisioning-via-Lark-OpenAP-409590f7e19e8174ab83cbe2df6087aa) | `server/services/lark/base_provision_service.py`, `server/models/system_config.py`, `server/routers/onboarding.py`, `server/services/knowledge/chat_scopes.py`, `server/services/knowledge/policy_sync.py` |
| EDL-0019 | [Kiến trúc Đa Nhà Cung Cấp LLM (ChatGPT, Anthropic, Google, Custom), Timeout Tùy biến & Giao diện Tinh giản Chuẩn Apple](https://app.notion.com/p/EDL-0019-Ki-n-tr-c-a-Nh-Cung-C-p-LLM-ChatGPT-Anthropic-Google-Custom-Timeout-T-y-bi-n-Gia-409590f7e19e81ad9f20fdd4b352ad47) | Partly Superseded by EDL-0075 | High | 2026-10-30 | [Notion Page](https://app.notion.com/p/EDL-0019-Ki-n-tr-c-a-Nh-Cung-C-p-LLM-ChatGPT-Anthropic-Google-Custom-Timeout-T-y-bi-n-Gia-409590f7e19e81ad9f20fdd4b352ad47) | `server/services/ai/gemini_client.py`, `server/services/user_settings_service.py`, `server/routers/onboarding.py`, `server/models/user_settings.py` |
| EDL-0020 | Kiến trúc Lark Store App (ISV Multi-Tenant SaaS) & Hạ tầng Vận hành Tập trung | Partly Superseded by EDL-0077 | High | 2026-10-31 | Local Record | `IMPLEMENTATION_PLAN_LARK_STORE_ISV_APP.md`, `server/services/lark/client.py`, `server/database/indexes.py` |
| EDL-0021 | [Kiến trúc Cấp phát Tri thức Đa Doanh nghiệp WeKnora & Auto-Provision Bitable (Giải pháp B - Admin DM + Screen Guide)](https://app.notion.com/p/EDL-0021-Ki-n-tr-c-C-p-ph-t-Tri-th-c-a-Doanh-nghi-p-WeKnora-Auto-Provision-Bitable-Gi-i-ph-p-B--40a590f7e19e8147bb04f7a17a1fdfea) | Approved | High | 2026-10-31 | [Notion Page](https://app.notion.com/p/EDL-0021-Ki-n-tr-c-C-p-ph-t-Tri-th-c-a-Doanh-nghi-p-WeKnora-Auto-Provision-Bitable-Gi-i-ph-p-B--40a590f7e19e8147bb04f7a17a1fdfea) | `server/services/knowledge/weknora_provision_service.py`, `server/services/lark/base_provision_service.py`, `server/routers/onboarding.py`, `server/templates/onboarding_wizard.html` |
| EDL-0022 | [Kiến trúc Kích hoạt 1-Click Lark Marketplace & Trải nghiệm Onboarding Đa Doanh nghiệp (Adaptive Dual-Mode Screen Guide)](https://app.notion.com/p/EDL-0022-Ki-n-tr-c-K-ch-ho-t-1-Click-Lark-Marketplace-Tr-i-nghi-m-Onboarding-a-Doanh-nghi-p-Ada-40a590f7e19e81668ddbfb633af33081) | Partly Superseded by EDL-0077 | High | 2026-10-31 | [Notion Page](https://app.notion.com/p/EDL-0022-Ki-n-tr-c-K-ch-ho-t-1-Click-Lark-Marketplace-Tr-i-nghi-m-Onboarding-a-Doanh-nghi-p-Ada-40a590f7e19e81668ddbfb633af33081) | `server/services/lark/card_builder.py`, `server/services/lark/handlers/tenant_lifecycle_handler.py`, `server/services/lark/handlers/owner_command_handler.py`, `server/templates/onboarding_wizard.html`, `server/routers/onboarding.py`, `server/tests/final_test/test_marketplace_onboarding_experience.py` |
| EDL-0023 | [Kiến trúc Điều Phối 100% Nút Bấm Thẻ Tương Tác (Button-Driven Interactive Card Hub) & Loại Bỏ Hoàn Toàn Command-Based DM](https://app.notion.com/p/EDL-0023-Ki-n-tr-c-i-u-Ph-i-100-N-t-B-m-Th-T-ng-T-c-Button-Driven-Interactive-Card-Hub-Lo-i-40a590f7e19e813dad9acc9c691feccc) | Approved | High | 2026-10-31 | [Notion Page](https://app.notion.com/p/EDL-0023-Ki-n-tr-c-i-u-Ph-i-100-N-t-B-m-Th-T-ng-T-c-Button-Driven-Interactive-Card-Hub-Lo-i-40a590f7e19e813dad9acc9c691feccc) | `server/services/lark/handlers/owner_command_handler.py`, `server/services/lark/card_builder.py`, `server/services/lark/handlers/card_action_handler.py`, `server/tests/final_test/test_marketplace_onboarding_experience.py`, `server/tests/final_test/phase_3_daily_digest_reporting/test_phase_3_daily_digest_reporting.py` |
| EDL-0024 | [Chuyển Dịch Cơ Sở Dữ Liệu Lên MongoDB Atlas Cloud Cluster & Bảo Mật Hạ Tầng Thông Tin Xác Thực](https://app.notion.com/p/EDL-0024-Chuy-n-D-ch-C-S-D-Li-u-L-n-MongoDB-Atlas-Cloud-Cluster-B-o-M-t-H-T-ng-Th-ng-Tin-X-c--40a590f7e19e817793d9de50574f4d70) | Approved | High | 2026-10-31 | [Notion Page](https://app.notion.com/p/EDL-0024-Chuy-n-D-ch-C-S-D-Li-u-L-n-MongoDB-Atlas-Cloud-Cluster-B-o-M-t-H-T-ng-Th-ng-Tin-X-c--40a590f7e19e817793d9de50574f4d70) | `server/core/config.py`, `server/database/db.py`, `server/database/indexes.py`, `.gitignore`, `.env`, `server/tests/final_test/` |
| EDL-0025 | Khắc Phục Lỗi Thiếu LARK_USER_OPEN_ID Khi Duyệt Bản Nháp & Cơ Chế Phân Giải 9 Cấp Bậc | Partly Superseded by EDL-0070 | High | 2026-10-31 | Local Record | `server/services/workflows/chat_workflow.py`, `server/services/lark/client.py`, `server/routers/onboarding.py`, `server/services/lark/messenger.py` |
| EDL-0026 | Kiến Trúc One-Click Setup 7 Bước Tự Động (ISV SaaS Zero-Touch Onboarding & Apple Minimalist UI) | Partly Superseded by EDL-0077 | High | 2026-10-31 | Local Record | `server/services/setup/one_click_setup_service.py`, `server/routers/setup.py`, `server/templates/setup_one_click.html`, `server/tests/final_test/test_one_click_setup.py` |
| EDL-0027 | Hợp Nhất Trải Nghiệm Setup & Onboarding (One-Click Setup + Progressive Customization Chuẩn SF Pro Light) | Approved | High | 2026-10-31 | Local Record | `server/templates/setup_one_click.html`, `server/services/setup/one_click_setup_service.py`, `server/routers/setup.py` |
| EDL-0028 | Khắc Phục Triệt Để Deadlock & Tối Ưu Hóa Cấp Phát Hạ Tầng Bước 5 (ISV Lock Separation & Parallel Provisioning) | Partly Superseded by EDL-0077 | High | 2026-10-31 | Local Record | `server/services/auth/isv_token_service.py`, `server/services/lark/bitable.py`, `server/services/lark/base_provision_service.py`, `server/services/setup/one_click_setup_service.py`, `server/main.py` |
| EDL-0029 | Tự Động Thích Ứng Schema Cột Lark Base (Adaptive Schema Field Mapping) & Khắc Phục Lỗi FieldNameNotFound | Approved | High | 2026-10-31 | Local Record | `server/services/lark/bitable.py`, `server/services/knowledge/chat_scopes.py`, `server/services/lark/dispatcher.py` |
| EDL-0030 | Dọn Dẹp & Chuẩn Hóa 100% Lark Base Tự Động (Zero-Junk-Column, Clean-State Provisioning & Vietnamese Schema) | Approved | High | 2026-10-31 | Local Record | `server/services/lark/base_provision_service.py`, `server/services/user_settings_service.py`, `server/services/setup/one_click_setup_service.py` |
| EDL-0031 | Chuẩn Hóa Cổng Đăng Nhập WeKnora Web Console (Cổng 80) & Cấp Quyền Admin Hệ Thống | Approved | High | 2026-10-31 | Local Record | `server/services/knowledge/weknora_provision_service.py`, `server/services/lark/card_builder.py`, `server/core/config.py`, `server/models/tenant.py` |
| EDL-0032 | Đồng Bộ Tri Thức WeKnora Đa Doanh Nghiệp (Multi-Tenant Dataset Routing, X-Tenant-ID Header & Dual Chat/Base Ingestion) | Approved | High | 2026-10-31 | Local Record | `server/services/knowledge/chat_scopes.py`, `server/services/knowledge/weknora_client.py`, `server/services/knowledge/policy_sync.py`, `server/services/lark/handlers/document_handler.py`, `server/services/lark/dispatcher.py` |
| EDL-0033 | Khắc Phục Lỗi 403 Forbidden WeKnora Upload: Chuyển Đổi Platform Scope Key, Chuẩn Hóa Tenant Registration & Shared Builtin Embedding Models | Approved | High | 2026-11-01 | Local Record | `server/services/knowledge/weknora_provision_service.py`, `server/services/knowledge/weknora_client.py`, `WeKnora-postgres` (`tenant_api_keys`, `models`, `knowledge_bases`) |
| EDL-0034 | Strict WeKnora Provisioning: Chỉ Ready sau khi Register/Login/KB thành công | Approved | High | 2026-11-01 | Local Record | `server/services/knowledge/weknora_provision_service.py`, `server/services/setup/one_click_setup_service.py`, `server/core/config.py` |
| EDL-0035 | [Kiến trúc Cô lập Dữ liệu Toàn diện Đa Doanh nghiệp (Zero Cross-Tenant Data Leakage & Scoped Execution Context)](https://app.notion.com/p/EDL-0035-Ki-n-tr-c-C-l-p-D-li-u-To-n-di-n-a-Doanh-nghi-p-Zero-Cross-Tenant-Data-Leakage-Scope-40b590f7e19e81dba391d6b1d6758166) | Approved | High | 2026-11-01 | [Notion Page](https://app.notion.com/p/EDL-0035-Ki-n-tr-c-C-l-p-D-li-u-To-n-di-n-a-Doanh-nghi-p-Zero-Cross-Tenant-Data-Leakage-Scope-40b590f7e19e81dba391d6b1d6758166) | `server/models/chat.py`, `server/database/db.py`, `server/services/workflows/digest_workflow.py`, `server/services/workflows/claim_workflow.py`, `server/services/workflows/draft_store.py`, `server/services/workflows/draft_workflow.py`, `server/services/lark/card_builder.py`, `server/services/lark/handlers/card_action_handler.py`, `server/services/lark/dispatcher.py`, `server/services/lark/bot_runner.py`, `server/services/lark/bitable.py`, `server/routers/scope.py`, `server/routers/digest.py`, `server/tests/final_test/test_cross_tenant_isolation_complete.py` |
| EDL-0036 | Strict Claims Scope Resolution: Tenant → Chat/Global Policy → Entity → Status → Relevance | Approved | High | 2026-11-01 | Local Record | `server/database/db.py`, `server/services/workflows/chat_workflow.py`, `server/services/knowledge/context_composer.py`, `server/tests/final_test/test_claims_knowledge_multi_tenant.py` |
| EDL-0037 | Durable One-Click Setup State & Tenant-Scoped P2 Guards | Approved | High | 2026-11-01 | Local Record | `server/services/setup/one_click_setup_service.py`, `server/database/db.py`, `server/database/indexes.py`, `server/services/lark/handlers/tenant_lifecycle_handler.py`, `server/services/workflows/digest_workflow.py`, `server/services/knowledge/weknora_client.py` |
| EDL-0038 | Complete Digest/Master Digest Tenant Scoping | Approved | High | 2026-11-01 | Local Record | `server/services/workflows/digest_workflow.py` |
| EDL-0039 | Bắt buộc App Credential, Tenant Token và User OAuth trong One-Click Setup | Partly Superseded by EDL-0077 | High | 2026-11-01 | Local Record | `server/services/setup/one_click_setup_service.py`, `server/routers/setup.py`, `server/services/auth/isv_token_service.py`, `server/templates/setup_one_click.html` |
| EDL-0040 | Chuẩn hóa Lark Webhook Verification và Tenant Context cho Bot Added Event | Approved | High | 2026-11-01 | Local Record | `server/services/lark/dispatcher.py`, `server/services/lark/messenger.py` |
| EDL-0041 | Tenant-scoped Custom App Registry và Runtime Client Pool cho một server nhiều Custom App | In progress | Critical | 2026-11-01 | Local Record | `docs/IMPLEMENTATION_PLAN_MULTI_CUSTOM_APP.md`, `server/services/lark_app_service.py`, `server/services/lark/runtime.py`, `server/services/auth/token_service.py` |
| EDL-0042 | Truyền tường minh WeKnora Tenant Mapping trong Bitable Webhook | Approved | High | 2026-11-01 | Local Record | `server/services/knowledge/chat_scopes.py`, `server/services/knowledge/weknora_client.py` |
| EDL-0043 | Owner Shield chỉ chống auto-reply, không override JEV Memory Routing | Approved | High | 2026-11-01 | Local Record | `server/services/workflows/chat_workflow.py`, `server/tests/final_test/phase_2_chat_intent_safety/test_phase_2_chat_intent_safety.py` |
| EDL-0044 | Truyền Speaker Role vào JEV để tránh Owner Memory Overfit | Approved | High | 2026-11-01 | Local Record | `server/services/ai/jev_classifier.py`, `server/services/workflows/chat_workflow.py` |
| EDL-0045 | Chuẩn hóa Log Pipeline theo Lifecycle và phân biệt Staging/Memory | Approved | Medium | 2026-11-01 | Local Record | `server/services/lark/dispatcher.py`, `server/services/lark/bot_runner.py`, `server/services/lark/handlers/member_message_handler.py`, `server/services/workflows/chat_queue.py`, `server/services/workflows/digest_workflow.py` |
| EDL-0046 | Tenant-scoped Digest Schedule từ cấu hình trợ lý | Approved | High | 2026-11-01 | Local Record | `server/routers/onboarding.py`, `server/services/user_settings_service.py`, `server/services/lark/bot_runner.py` |
| EDL-0047 | Scheduler gửi Master Digest bằng Custom App của đúng tenant | Approved | Critical | 2026-11-01 | Local Record | `server/services/lark_app_service.py`, `server/services/workflows/digest_workflow.py` |
| EDL-0048 | Digest WeKnora Sync và Card Callback phải giữ tenant/App context | Approved | Critical | 2026-11-01 | Local Record | `server/services/knowledge/weknora_client.py`, `server/services/workflows/digest_workflow.py`, `server/services/lark/messenger.py` |
| EDL-0049 | JEV định tuyến tình huống khẩn cấp có yêu cầu phương án sang Draft Approval | Approved | High | 2026-11-01 | Local Record | `server/services/ai/jev_classifier.py` |
| EDL-0050 | Refresh OAuth theo từng Custom App/tenant và vô hiệu hóa token lệch App | Approved | Critical | 2026-11-01 | Local Record | `server/services/auth/token_service.py` |
| EDL-0051 | PolicySync semantic parser cho Lark Base mention/link | Approved | High | 2026-11-01 | Local Record | `server/services/knowledge/policy_sync.py`, `server/tests/final_test/test_policy_sync_parser.py` |
| EDL-0052 | Bật rich-text field response cho PolicySync Bitable records | Approved | High | 2026-11-01 | Local Record | `server/services/knowledge/policy_sync.py` |
| EDL-0053 | PolicySync phải bind Lark runtime theo tenant trước khi đọc tài liệu | Approved | Critical | 2026-11-01 | Local Record | `server/services/knowledge/policy_sync.py`, `server/services/lark/runtime.py` |
| EDL-0054 | Không ping token legacy khi server chạy tenant-scoped Custom Apps | Approved | High | 2026-11-01 | Local Record | `server/services/lark/bot_runner.py` |
| EDL-0055 | Resolve owner open_id theo đúng runtime Custom App | Approved | Critical | 2026-11-01 | Local Record | `server/services/workflows/chat_workflow.py`, `server/services/lark/runtime.py` |
| EDL-0056 | Bỏ qua legacy primary user token khi đã có scoped Custom Apps | Approved | Critical | 2026-11-01 | Local Record | `server/services/auth/token_service.py`, `server/services/lark/client.py` |
| EDL-0057 | Tự động phân giải App ID theo Tenant và dùng trực tiếp Valid Token trong luồng Duyệt Draft | Approved | Critical | 2026-11-01 | Local Record | `server/services/auth/token_service.py`, `server/services/lark/messenger.py`, `server/services/workflows/draft_workflow.py` |
| EDL-0058 | Chuẩn hóa Card Action Callback Response Schema và Đồng bộ Custom App Sender cho In-place Card Update | Approved | High | 2026-11-01 | Local Record | `server/services/lark/messenger.py`, `server/services/lark/handlers/card_action_handler.py`, `server/services/workflows/chat_workflow.py` |
| EDL-0059 | Mở rộng kiểm tra Policy Knowledge Base Scopes trong Chat Workflow Document Isolation Filter | Approved | High | 2026-11-01 | Local Record | `server/services/workflows/chat_workflow.py` |
| EDL-0060 | Shared Sent Message Cache chống Loopback Webhook và Chuẩn hóa Danh tính Lãnh đạo trong Staging | Approved | Critical | 2026-11-01 | Local Record | `server/services/lark/dispatcher.py`, `server/services/lark/messenger.py`, `server/services/lark/handlers/member_message_handler.py`, `server/services/workflows/digest_workflow.py` |
| EDL-0061 | Khắc phục triệt để Lark Error Code 200341: Chuẩn hóa Sync Response In-place Card Update và Loại bỏ Redundant OpenAPI Patch | Approved | Critical | 2026-11-01 | Local Record | `server/services/lark/handlers/card_action_handler.py`, `server/services/lark/dispatcher.py`, `server/routers/policy.py` |
| EDL-0062 | Tinh giản Giao diện & Luồng Duyệt Bản Nháp: Loại bỏ Tính năng "Sửa AI" (AI Rewrite) | Approved | Medium | 2026-11-01 | Local Record | `server/services/lark/card_builder.py`, `server/services/lark/handlers/card_action_handler.py`, `server/services/ai/` |
| EDL-0063 | Triển khai Form Textarea Trực Tiếp Trên Lark Interactive Card (Card JSON 2.0) Cho Luồng Tự Sửa Bản Nháp | Approved | High | 2026-11-01 | Local Record | `server/services/lark/card_builder.py`, `server/services/lark/dispatcher.py`, `server/services/lark/handlers/card_action_handler.py`, `server/tests/final_test/phase_2_chat_intent_safety/test_phase_2_chat_intent_safety.py` |
| EDL-0064 | Tối Ưu Hóa ThreadPoolExecutor, Caching Motor Client Per Loop & Tăng Timeout Card Action Lên 10s | Approved | High | 2026-11-01 | Local Record | `server/services/lark/dispatcher.py`, `server/database/db.py` |
| EDL-0065 | Xử Lý Triệt Để Lỗi 200341 & Tin Nhắn Kép: Non-Blocking Background Delivery Executor, Multi-Channel Dedup Cache & Card JSON 2.0 Status Card | Approved | Critical | 2026-11-01 | Local Record | `server/services/workflows/draft_workflow.py`, `server/services/lark/handlers/card_action_handler.py`, `server/services/lark/card_builder.py` |
| EDL-0066 | Khắc Phục Triệt Để Lỗi 200341 & 'Không Xác Định Được Hành Động': Lazy-load Lark Service (<50ms Callback Response), Mở Rộng Button Name Mapping & Idempotency Sent Guard | Approved | Critical | 2026-11-02 | Local Record | `server/services/lark/handlers/card_action_handler.py`, `server/services/lark/dispatcher.py`, `server/tests/final_test/phase_2_chat_intent_safety/test_phase_2_chat_intent_safety.py` |
| EDL-0067 | Kiến Trúc Dashboard Giám Sát Vận Hành Doanh Nghiệp: HMAC-SHA256 Signed URLs, Apple Minimalist UI Micro-Charts SVG & Zero Cross-Tenant Leakage | Approved | Critical | 2026-11-02 | Local Record | `server/services/tenant_metrics_service.py`, `server/routers/dashboard.py`, `server/templates/tenant_dashboard.html`, `server/services/lark/card_builder.py`, `server/services/lark/handlers/card_action_handler.py`, `server/tests/final_test/test_tenant_isolated_dashboard.py` |
| EDL-0068 | Centralized Multi-Tenant Token Orchestration: TenantTokenManager, Per-Tenant Caching + Locking, Zero .env Fallback in Production | Partly Superseded by EDL-0070 | Critical | 2026-11-02 | Local Record | `server/services/auth/tenant_token_manager.py`, `server/models/auth.py`, `server/services/auth/token_service.py`, `server/services/lark/bitable.py`, `server/services/lark/client.py`, `server/tests/auth/test_token_broker.py` (thay hai test `test_tenant_token_manager*.py` đã xoá) |
| EDL-0069 | Single Source of Truth Refactor: All Business Logic Token Access via TenantTokenManager (Async/Sync Wrapper Strategy) | Partly Superseded by EDL-0070 | Critical | 2026-11-02 | Local Record | `server/services/lark/base_provision_service.py`, `server/services/setup/one_click_setup_service.py`, `server/services/lark/messenger.py`, `server/services/lark/runtime.py`, `server/services/lark/bitable.py` |
| EDL-0070 | Tra Cứu Có Hợp Đồng: Token Loop Riêng + TokenBroker 3 Chiều, TenantResourceResolver Fail-Closed, State Machine Tenant & OAuth Mang Danh Tính App | Approved | Critical | 2026-11-02 | Local Record (chưa đồng bộ Notion — không có Notion MCP) | `server/core/token_loop.py`, `server/core/tenant_errors.py`, `server/services/auth/tenant_token_manager.py`, `server/services/tenancy/tenant_resolver.py`, `server/services/tenancy/tenant_state.py`, `server/services/auth/oauth_state_service.py`, `server/services/auth/tenant_refresh_sweeper.py`, `server/services/lark/tenant_error_reply.py`, `server/services/lark/bitable.py`, `server/database/db.py`, `scripts/cleanup_test_tenant.py`, `scripts/audit_tenant_config_readonly.py`, `docker-compose.prod.yml` |
| EDL-0071 | [Rebuild Toàn Diện Tri Thức Chính Sách Khi Đồng Bộ & Cô Lập Tuyệt Đối Tài Liệu Nhóm Chat](https://app.notion.com/p/EDL-0071-Rebuild-To-n-Di-n-Tri-Th-c-Ch-nh-S-ch-Khi-ng-B-C-L-p-Tuy-t-i-T-i-Li-u-Nh-m-Chat-40c590f7e19e818aac0ec3ba7b2918ff) | Approved | High | 2026-11-03 | [Notion Page](https://app.notion.com/p/EDL-0071-Rebuild-To-n-Di-n-Tri-Th-c-Ch-nh-S-ch-Khi-ng-B-C-L-p-Tuy-t-i-T-i-Li-u-Nh-m-Chat-40c590f7e19e818aac0ec3ba7b2918ff) | `server/services/knowledge/weknora_client.py`, `server/services/knowledge/policy_sync.py`, `server/services/workflows/chat_workflow.py` |
| EDL-0072 | Định danh Webhook & Card Action Tuyệt đối Theo App ID (Deterministic Multi-Tenant Routing) — Path & Query Param Routes, Zero Brute-Force | Approved | Critical | 2026-11-03 | Local Record (chưa đồng bộ Notion) | `server/routers/lark.py`, `server/services/lark/messenger.py`, `server/tests/lark/test_multitenant_webhook_routing.py`, `docs/lark_event_subscription.md`, `docs/IMPLEMENTATION_PLAN_APP_ID_WEBHOOK_ROUTING.md` |
| EDL-0073 | Triệt tiêu Vòng lặp Đốt Token: Deduplication-First Policy Sync & Nâng Chu kỳ ChatScope Sync | Approved | High | 2026-11-03 | Local Record (chưa đồng bộ Notion) | `server/services/lark/bot_runner.py`, `server/services/knowledge/policy_sync.py` |
| EDL-0074 | Khắc Phục Triệt Để 4 Điểm Rò Rỉ Dữ Liệu Cross-Tenant & Cross-Group (Strict Claim Isolation, Scoped Attachment/Doc Parsing, Deterministic Multi-Tenant Entity ID & Compound Unique Index) | Approved | Critical | 2026-11-03 | Local Record (chưa đồng bộ Notion) | `server/services/knowledge/context_composer.py`, `server/services/knowledge/doc_parser.py`, `server/services/lark/handlers/document_handler.py`, `server/services/lark/runtime.py`, `server/services/ai/llm_extractor.py`, `server/database/indexes.py`, `scripts/migrate_entity_index.py`, `server/tests/final_test/test_data_leakage_fixes.py` |
| EDL-0075 | [Unified Fail-Closed BYOK, AI Config Manager tập trung, Mặc định gemini-flash-latest & JEV BYOK trên UI](https://app.notion.com/p/EDL-0075-Unified-Fail-Closed-BYOK-AI-Config-Manager-t-p-trung-M-c-nh-gemini-flash-latest-JEV--413590f7e19e814f8786ca5ca1b1c737) | Partly Superseded by EDL-0076 | Critical (Notion: High) | 2026-11-09 | [Notion Page](https://app.notion.com/p/EDL-0075-Unified-Fail-Closed-BYOK-AI-Config-Manager-t-p-trung-M-c-nh-gemini-flash-latest-JEV--413590f7e19e814f8786ca5ca1b1c737) | `server/services/ai/ai_config_manager.py`, `server/services/ai/model_catalog.py`, `server/services/ai/llm_client.py` (thay `gemini_client.py` đã xoá ở EDL-0076), `server/services/ai/jev_classifier.py`, `server/services/user_settings_service.py`, `server/models/user_settings.py`, `server/routers/onboarding.py`, `server/templates/onboarding_wizard.html`, `server/templates/setup_one_click.html` |
| EDL-0076 | [Refactor LLMClient đa provider, chuẩn hóa Models & Schema MongoDB, đưa Cost Telemetry ra .env và đo thinking_tokens](https://app.notion.com/p/EDL-0076-Refactor-LLMClient-a-provider-chu-n-h-a-Models-Schema-MongoDB-a-Cost-Telemetry-ra--413590f7e19e814cb219c7328239f002) | Approved | Critical (Notion: High) | 2026-11-09 | [Notion Page](https://app.notion.com/p/EDL-0076-Refactor-LLMClient-a-provider-chu-n-h-a-Models-Schema-MongoDB-a-Cost-Telemetry-ra--413590f7e19e814cb219c7328239f002) | `server/models/llm.py`, `server/models/telemetry.py`, `server/services/ai/llm_client.py` (xóa cứng `gemini_client.py`), `server/services/ai/model_catalog.py`, `server/core/config.py`, `server/decorators/cost_telemetry.py`, `server/database/indexes.py`, `scripts/migrate_llm_schema.py` |
| EDL-0077 | [Hợp nhất Token Broker & OAuth Gate tuyến tính, phân quyền Bot/User Token Fail-Closed, mã hóa lark_auth và gỡ bỏ hoàn toàn luồng ISV Store App](https://app.notion.com/p/EDL-0077-H-p-nh-t-Token-Broker-OAuth-Gate-tuy-n-t-nh-ph-n-quy-n-Bot-User-Token-Fail-Closed-m-h-414590f7e19e8159aea0e9a7ea0174c1) | Approved | Critical (Notion: High) | 2026-11-10 | [Notion Page](https://app.notion.com/p/EDL-0077-H-p-nh-t-Token-Broker-OAuth-Gate-tuy-n-t-nh-ph-n-quy-n-Bot-User-Token-Fail-Closed-m-h-414590f7e19e8159aea0e9a7ea0174c1) | `server/services/auth/{tenant_token_manager.py,token_service.py,token_verifier.py}` (xóa cứng `isv_token_service.py`), `server/services/tenancy/{tenant_resolver.py,tenant_state.py}`, `server/services/lark/{client.py,messenger.py,bitable.py,base_provision_service.py,card_builder.py,handlers/tenant_lifecycle_handler.py}`, `server/services/workflows/draft_workflow.py`, `server/database/scoped_query.py`, `scripts/migrate_lark_auth_encryption.py` |


## Rules
- Add entries only for consequential technical decisions.
- Use the real Notion URL/ID returned by the connected MCP.
- Keep old decisions for history; mark replaced decisions as `Superseded` and link the replacement.
- If Notion sync is unavailable, say so and keep a local draft rather than pretending it synced.



---

## EDL-0069: Single Source of Truth Refactor - All Business Logic Token Access via TenantTokenManager

**Status:** Approved  
**Impact:** Critical  
**Date:** 2026-11-02  
**Context:** WS7 - Consolidate scattered token access patterns into centralized TenantTokenManager

### Problem Statement
Sau khi xây dựng TenantTokenManager (EDL-0068), phát hiện 5 bypass locations còn gọi trực tiếp `isv_token_service` hoặc `token_service` thay vì qua manager:
1. `base_provision_service.py:114` - gọi `isv_token_service.get_tenant_access_token()`
2. `one_click_setup_service.py:352` - gọi `isv_token_service.get_tenant_access_token()`
3. `messenger.py:299, 541` (2 chỗ) - gọi `token_service.get_valid_user_token()`
4. `runtime.py:39, 54` (2 chỗ) - gọi `token_service.get_valid_user_token()`
5. `bitable.py:186` - gọi sync `isv_token_service.get_tenant_access_token_sync()`

**Risks:**
- Bypass cache = mất performance benefit của TenantTokenManager
- Bypass locking = race condition risk khi concurrent requests
- Không consistent về token refresh strategy
- Khó debug vì token flow phân tán ở nhiều chỗ

### Decision

**Chosen:** Refactor tất cả 5 locations để gọi qua `tenant_token_manager.get_token()` as single source of truth

**Implementation strategy:**
1. **Locations #1-2 (Bot Token):** Replace `isv_token_service.get_tenant_access_token()` → `tenant_token_manager.get_token(token_type="bot")`
2. **Locations #3-4 (User Token):** Replace `token_service.get_valid_user_token()` → `tenant_token_manager.get_token(token_type="user")`
3. **Location #5 (Sync Wrapper):** Create 3-tier solution for backward compatibility:
   - `get_tenant_access_token_async()`: New async version using `tenant_token_manager.get_token()`
   - `get_tenant_access_token()`: Sync wrapper checking event loop state:
     - No running loop → use `asyncio.run()` safely
     - Loop already running → fall back to `_get_tenant_access_token_fallback()`
   - `_get_tenant_access_token_fallback()`: Old implementation (not using TenantTokenManager) for edge cases only

**Why 3-tier for bitable.py:**
- `bitable.py` có 3 sync callers: `_get_headers()`, `subscribe_base_events()`, `get_bot_chats()`
- Migrating tất cả sync callers sang async = breaking change lớn (ảnh hưởng nhiều files)
- 3-tier strategy = minimal change now + clear migration path later

### Alternatives Considered

**Option A: Full async migration (rejected)**
- Chuyển tất cả sync callers (`_get_headers`, `subscribe_base_events`, `get_bot_chats`) sang async
- **Pros:** Clean architecture, no fallback logic
- **Cons:** Breaking change lớn, ảnh hưởng nhiều files, high risk
- **Why rejected:** Violates "thay đổi nhỏ nhất giải quyết đúng vấn đề" principle (AGENTS.md)

**Option B: Keep bypass locations unchanged (rejected)**
- Giữ nguyên 5 locations gọi trực tiếp token services
- **Pros:** Zero risk, no code change
- **Cons:** Không đạt single source of truth, cache bypass, race condition risk
- **Why rejected:** Không giải quyết root problem

### Verification

**Test Results:**
- Full test suite: **46/46 tests PASSED (100%)** in 14.36s
  - 30 unit tests (test_tenant_token_manager.py)
  - 7 integration tests (test_tenant_token_manager_integration.py)
  - 9 ISV token service tests (test_isv_token_service.py)
- Zero regressions detected

**Architecture verification:**
- ✅ All 5 bypass locations now flow through TenantTokenManager
- ✅ Per-tenant cache + locking consistency achieved
- ✅ Backward compatibility preserved (sync wrappers work)
- ✅ Fallback logic tested (event loop edge case)

### Trade-offs

**Benefits:**
- Single source of truth = easier debugging (one place to check token flow)
- Cache consistency = 99% requests từ RAM, không hit MongoDB
- Locking consistency = zero race condition on concurrent token refresh
- Monitoring centralized = one stats method for all token access

**Costs:**
- Sync wrapper complexity in bitable.py (3 functions instead of 1)
- Technical debt: sync callers nên migrate sang async trong future sprint
- Edge case handling: event loop detection logic thêm 10 lines code

### Implementation Details

**Files Modified:**
1. `server/services/lark/base_provision_service.py` - line 114: Bot token via TenantTokenManager
2. `server/services/setup/one_click_setup_service.py` - line 352: Bot token via TenantTokenManager
3. `server/services/lark/messenger.py` - lines 299, 541: User token via TenantTokenManager
4. `server/services/lark/runtime.py` - lines 39, 54: User token via TenantTokenManager
5. `server/services/lark/bitable.py` - line 186: 3-tier async/sync/fallback strategy

**Key Code Patterns:**

Bot token access:
```python
from services.auth.tenant_token_manager import tenant_token_manager
token = await tenant_token_manager.get_token(
    tenant_key=eff_tenant,
    token_type="bot"
)
```

User token access:
```python
from services.auth.tenant_token_manager import tenant_token_manager
token = await tenant_token_manager.get_token(
    tenant_key=eff_tenant,
    token_type="user"
)
```

Sync wrapper pattern (bitable.py):
```python
def get_tenant_access_token(self, force_refresh=False, tenant_key=None):
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return self._get_tenant_access_token_fallback(...)  # Edge case
        else:
            return asyncio.run(self.get_tenant_access_token_async(...))
    except RuntimeError:
        return asyncio.run(self.get_tenant_access_token_async(...))
```

### Future Work

**Technical Debt:**
- Migrate `_get_headers()`, `subscribe_base_events()`, `get_bot_chats()` sang async
- Remove `_get_tenant_access_token_fallback()` after migration complete
- Add deprecation warning to sync wrapper

**Monitoring:**
- Track fallback usage rate in production logs
- Alert if fallback used > 5% of time (indicates migration needed)

### Related Decisions
- **EDL-0068:** TenantTokenManager architecture foundation
- **EDL-0035:** Multi-tenant data isolation (tenant_key scoping)
- **EDL-0028:** ISV deadlock fix (separate locks)

### References
- Test suite: `server/tests/auth/test_tenant_token_manager.py` — **đã xoá**, thay bằng `server/tests/auth/test_token_broker.py` (EDL-0070)
- Integration tests: `server/tests/auth/test_tenant_token_manager_integration.py` — **đã xoá**, thay bằng `server/tests/tenancy/test_tenant_resolver.py` + `server/tests/auth/test_tenant_refresh_sweeper.py` (EDL-0070)
- Architecture doc: `docs/project-memory/PROJECT_CONTEXT.md` (TenantTokenManager → TokenBroker, EDL-0070)
- Handoff status: `docs/project-memory/HANDOFF.md` (WS7 completion; các bước kế tiếp thuộc WS8 / EDL-0070)

---

## EDL-0070: Tra Cứu Có Hợp Đồng — Token Loop Riêng, TokenBroker 3 Chiều, TenantResourceResolver Fail-Closed, State Machine Tenant & OAuth Mang Danh Tính App

**Status:** Approved (code + test đã xong trên nhánh `fix/tenant-resolution-token`; chưa commit, chưa deploy)
**Impact:** Critical
**Date:** 2026-11-02
**Context:** Kế hoạch "Sửa Tenant Resolution & Token Flow" (6 giai đoạn GĐ0–GĐ6). Supersede một phần EDL-0068, EDL-0069 và EDL-0025.

### Problem Statement
Không có một nơi duy nhất trả lời "cấu hình và token này thuộc tenant nào". Mỗi chỗ tự đoán theo thứ tự
`tenant → App bất kỳ → .env`, và khi đoán hỏng thì **lặng lẽ dùng dữ liệu của doanh nghiệp khác** thay vì báo lỗi:
- `bitable` / `isv_token_service` / `base_provision_service` tự resolve App credential: thiếu `tenant_key` là lấy
  `settings.LARK_APP_ID/SECRET` hoặc "App mới nhất trong DB" ⇒ token của doanh nghiệp A gửi cho doanh nghiệp B.
- Cache token chỉ theo `(tenant_key, token_type)`: khi một tenant đổi App, token của App cũ vẫn được dùng.
- Singleton `lark_base_service` bị nhiều luồng ghi đè `app_token/table_id/user_access_token` ⇒ hai request song song đọc/ghi nhầm Base.
- `oauth_states` không tồn tại: state ủy quyền là chuỗi tự sinh, không gắn (tenant, App); `exchange_code_for_token`
  chấp nhận thiếu credential và còn ghi `_id="primary_user_token"` (danh tính dùng chung mọi tenant).
- `resolve_effective_owner_open_id()` (EDL-0025) leo 9 bậc, trong đó `.env`, "tenant bất kỳ", `system_config` toàn cục
  và `primary_user_token` có thể trả lãnh đạo của tenant khác làm `owner_id` của PendingDraft.
- Deadlock cross-loop: `asyncio.run()` trong worker thread + `asyncio.Lock` của manager tạo trên loop khác.

### Decision
**"Đoán" → "tra cứu có hợp đồng". Thiếu dữ liệu luôn là exception có kiểu, không bao giờ có giá trị thay thế.**

1. **`server/core/token_loop.py`**: một daemon thread chạy một event loop cho toàn bộ việc lấy token.
   `submit()` cho caller sync, `asubmit()` cho caller async (await trực tiếp nếu đang chạy chính trên loop đó).
2. **`server/core/tenant_errors.py`**: `TenantContextMissing` 400, `TenantNotFound`/`TenantNotReady`/
   `TenantConfigIncomplete`/`AppCredentialMissing` 409, `UserTokenMissing` 401, `TokenUnavailable` 503 — mỗi lớp tự
   mang `error_code` + `http_status`; `main.py` đăng ký handler một lần cho hai họ lỗi nên **router không tự phiên dịch**.
3. **TokenBroker** (`services/auth/tenant_token_manager.py`): cache key **3 chiều `(tenant_key, app_id, kind)`**,
   single-flight theo key + double-check, buffer hết hạn 300s, provider không cache/không fallback, **không bao giờ trả `""`**.
4. **`services/tenancy/tenant_resolver.py`**: một chỗ duy nhất trả `TenantResources` theo hợp đồng 6 bước fail-closed
   (tenant_key → doc `tenants` → `status == "ready"` → credential của **chính tenant** → `app_id` khớp → field bắt buộc),
   cache RAM 60s + `invalidate()`. Đã xoá `_resolve_app_credentials_*` và mọi `or settings.*` trong danh sách kế hoạch.
5. **`LarkBaseService.for_tenant()/for_policy_table()`**: không còn ghi đè singleton; instance tương thích import mà
   thiếu tenant thì raise. `dataset_id` của WeKnora là tham số bắt buộc.
6. **OAuth mang danh tính App**: collection `oauth_states` (TTL 10 phút, `find_one_and_update` dùng một lần) gắn
   `(tenant_key, app_id, purpose)`; `/auth/lark/login` bắt buộc `tenant_key`; `exchange_code_for_token` bắt buộc
   `app_id + app_secret + expected_tenant_key`, từ chối profile thuộc tenant khác và **không ghi** `primary_user_token`.
7. **`services/tenancy/tenant_state.py`**: state machine trên field `status` có sẵn + **invalidation hub** — mọi
   chuyển trạng thái, `register_app`, `link_tenant` đều gọi `tenant_resolver.invalidate()` và `token_broker.invalidate()`.
   `mark_ready()` chạy kiểm tra của resolver trước khi set `ready`; lỗi pipeline ⇒ `provisioning_failed`; UI setup có nút "Thử lại".
8. **`tenant_refresh_sweeper`** thay `start_token_refresh_loop()`: mỗi 10 phút duyệt `tenants` có `status="ready"`, lỗi chỉ log.
9. **Không làm lease Mongo cho refresh_token**: production là **1 container / 1 uvicorn worker**, cache RAM đủ.
   *Điều kiện hết hiệu lực:* nếu scale ≥ 2 replica phải thêm lease Mongo cho `refresh_token` **trước** khi bật sweeper.
10. **`resolve_effective_owner_open_id()` còn 7 bậc và chỉ nguồn thuộc tenant**: bỏ `.env`, bỏ query "tenant bất kỳ",
    `user_settings`/`system_config` chỉ được tin khi document mang `tenant_key` khớp; bỏ đọc `primary_user_token`.
    `_sync_runtime_admin_open_id()` không còn ghi `settings.LARK_USER_OPEN_ID` (bôi bẩn danh tính toàn process).

### Phương án đã loại
- **Cache RAM 2 chiều `(tenant, kind)` của EDL-0068:** đủ khi một tenant chỉ có một App vĩnh viễn; không đủ khi tenant đổi App.
- **Lease/lock trên MongoDB:** từ chối vì 1 replica; thêm độ phức tạp không giải quyết lỗi nào trong bối cảnh hiện tại.
- **`_get_tenant_access_token_fallback()` 3 tầng của EDL-0069:** nhánh "cứ chạy tiếp" chính là đường rò rỉ; xoá thay vì giữ làm debt.
- **Giữ `.env` cho dev:** giả định của kế hoạch là dev cũng tạo tenant qua luồng setup, nên không còn "chế độ .env".
- **Để router tự `HTTPException(status_code=err.http_status, detail=str(err))`:** giữ đúng mã 409 nhưng mất `error_code`/`tenant_key` trong body.

### Hệ quả & Rủi ro còn lại
- Breaking change có chủ đích ở tầng API: `/auth/lark/login` đòi `tenant_key`; `/auth/lark/exchange` trả body lỗi có cấu trúc.
- `scripts/cleanup_test_tenant.py` mặc định `--dry-run`; chỉ ghi `--apply` khi người dùng xác nhận (chưa chạy trên production).
- Atlas không truy cập được từ máy dev phiên này (`SSL: TLSV1_ALERT_INTERNAL_ERROR`) ⇒ **toàn bộ verification chạy trên
  MongoDB local** (`mongodb://localhost:27017`, DB `LarkAssistant_test`); cần chạy lại audit + suite trên Atlas khi deploy.
- D2: registration/app `19a84399cc971978` (App `cli_aa6c6ae8baf85e11`, theo `HANDOFF.md` 2026-11-02) vẫn cần người dùng
  cung cấp App Secret qua `register_app` + `link_tenant`; nếu secret đã mất thì tenant ở `provisioning_failed` và setup lại.
  Agent **không** tự sinh hay đoán credential.
- `docker-compose.prod.yml` từng chứa MONGO_URL Atlas kèm mật khẩu trong Git history ⇒ người dùng cần **đổi mật khẩu Atlas**.

### Verification (bằng chứng thực tế)
- `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests -q`
  → **250 passed, 3 warnings in 25.04s** (baseline GĐ0: **117 passed / 11 failed / 37 errors**).
- `import main` chạy sạch; `app.exception_handlers` gồm `TenantResolutionError`, `TokenUnavailable`, `OAuthStateError`.
- Test mới theo từng mục kế hoạch: T1 `tests/auth/test_token_loop_concurrency.py`; T3/T4 `tests/auth/test_token_broker.py`;
  T7/T8/C1 `tests/tenancy/test_tenant_resolver.py`; Sentinel `tests/tenancy/test_sentinel_env.py`;
  C3 `tests/tenancy/test_base_service_tenant_isolation.py`; state machine `tests/tenancy/test_tenant_state_machine.py`;
  sweeper `tests/auth/test_tenant_refresh_sweeper.py`; T5/T6 `tests/auth/test_oauth_login_flow_contract.py` +
  `tests/auth/test_oauth_state_service.py`; GĐ5 chat `tests/lark/test_tenant_error_reply.py`, HTTP
  `tests/final_test/test_tenant_error_http_mapping.py`; owner identity `tests/final_test/test_owner_open_id_tenant_scoped.py`.
- Test cũ dựa vào fallback `.env` đã viết lại theo hợp đồng mới (ghi rõ trong báo cáo hồi quy):
  `tests/final_test/test_base_auto_provision.py`, `test_isv_token_service.py`, `test_one_click_setup.py`,
  `test_event_ingress_multi_tenant.py`, `test_weknora_bitable_provisioning.py`, `phase_3_daily_digest_reporting`.
- `scripts/audit_tenant_config_readonly.py` thêm mục 9 (state machine + `app_id` khớp giữa `tenants` và
  `lark_app_credentials`): trên DB seed local phát hiện 1 status lạ, 3 vi phạm hợp đồng, 1 lệch `app_id`.
- `docker compose --env-file /tmp/empty.env -f docker-compose.prod.yml config` → EXIT=1,
  `required variable MONGO_URL is missing a value` (fail-fast khi thiếu secret).

### Related Decisions
- **Supersede một phần EDL-0068** (cache 2 chiều, provider fallback, hai test `test_tenant_token_manager*.py`).
- **Supersede một phần EDL-0069** (3-tier sync wrapper + `_get_tenant_access_token_fallback` trong `bitable.py`).
- **Supersede một phần EDL-0025** (bậc 2/3-"tenant bất kỳ"/5/6 của thang phân giải owner open_id).
- Liên quan: EDL-0035 (isolation), EDL-0041 (multi Custom App runtime), EDL-0028 (ISV locks), EDL-0024 (Atlas) — EDL-0024 cần rotation.

### Notion
**Chưa đồng bộ Notion**: phiên này không có Notion MCP (chỉ `browser-use`, `genui`). Đây là Local Record.

### References
- Plan: `Tenant_Resolution_Token_Fix_f9f873e1.md` (cache của IDE), 6 giai đoạn GĐ0–GĐ6 + Test Plan.
- Code chính: `server/core/token_loop.py`, `server/core/tenant_errors.py`, `server/services/auth/tenant_token_manager.py`,
  `server/services/tenancy/{tenant_resolver,tenant_state}.py`, `server/services/auth/{oauth_state_service,tenant_refresh_sweeper}.py`,
  `server/services/lark/tenant_error_reply.py`, `scripts/cleanup_test_tenant.py`, `scripts/audit_tenant_config_readonly.py`.
- Handoff: `docs/project-memory/HANDOFF.md` (WS8).

---

## EDL-0071: Rebuild Toàn Diện Tri Thức Chính Sách Khi Đồng Bộ & Cô Lập Tuyệt Đối Tài Liệu Nhóm Chat

**Status:** Approved  
**Impact:** High  
**Date:** 2026-11-03  
**Context:** Đồng bộ chính sách từ Lark Base sang WeKnora phải rebuild tài liệu thay vì sinh duplicate, đồng thời kiểm tra và gia cố cô lập tài liệu giữa các nhóm chat.

### Problem Statement
1. **Trùng lặp chính sách:** Khi người dùng cập nhật nội dung Lark Docs và bấm nút "Đồng bộ ngay", WeKnora tính toán file_hash khác nên tạo ra thêm một tài liệu mới song song với tài liệu cũ, khiến KB chứa nhiều bản sao với chunks lỗi thời.
2. **Nguy cơ rò rỉ tài liệu giữa các nhóm chat:** Tất cả các nhóm chat của cùng tenant chia sẻ chung `weknora_default_dataset_id`. Nếu một nhóm có 0 tài liệu được cấu hình (`not has_group_docs`), trước đây code bỏ qua khối kiểm tra allowlist dẫn đến việc toàn bộ tài liệu của nhóm khác bị lọt vào ngữ cảnh trả lời.

### Decision & Implementation
1. **WeKnora Client Extensions (`weknora_client.py`):**
   - Triển khai `list_knowledges(dataset_id, page, page_size, tenant_id)` gọi `GET /api/v1/knowledge-bases/{dataset_id}/knowledge`.
   - Triển khai `delete_knowledge(knowledge_id, tenant_id)` gọi `DELETE /api/v1/knowledge/{knowledge_id}` dọn dẹp triệt để chunks và vector embeddings.
2. **Policy Rebuild Pipeline (`policy_sync.py`):**
   - Triển khai hàm `_upload_or_rebuild`: Kiểm tra tài liệu trùng tên trong KB chính sách. Nếu tài liệu bị thay đổi nội dung hoặc đang gọi sync cưỡng bức (`force=True`), thực hiện xóa bản ghi cũ trước, đợi worker Asynq của WeKnora xác nhận xóa hoàn tất, sau đó mới nạp file bytes mới. Kết quả là WeKnora bóc tách và rebuild toàn bộ chunks/vectors mà không có duplicate.
3. **Chat Group Strict Document Isolation (`chat_workflow.py`):**
   - Bổ sung rào chắn cho nhóm có 0 tài liệu: Nếu `not has_group_docs`, hoàn toàn không truy vấn `project_dataset_id` và drop 100% chunks ngoài phạm vi chính sách.
   - Chuyển so khớp tên tài liệu sang exact base-name matching và tiền tố tối thiểu 5 ký tự để tránh false positive.
   - Thắt chặt kiểm tra `policy_kb_ids` để các file tài liệu dự án chứa từ khóa chính sách không thể vượt rào kiểm soát.

### Verification
- **Rebuild Policy:** Test gọi `POST /policy/sync?tenant_key=19835e79ba9c9942&force=true`: Log xác nhận `🔄 Rebuild 'Lark DocX (dox...).md': Đang xoá bản cũ để rebuild lại chỉ mục... ✔ Đã nạp & rebuild thành công`. `list_knowledges` xác nhận chỉ có duy nhất 1 tài liệu trong KB.
- **Cô Lập Nhóm Chat:** Test gọi `process_chat_pipeline`:
  + Nhóm `test` (0 files): `num_chunks: 0` (không có chunk nào của nhóm OmniOps bị rò rỉ).
  + Nhóm `OmniOps` (11 files): `num_chunks: 3` (`03_architecture.md`, `OmniOps_Project_Overview.docx.md`).

### Notion
- Notion Page: [EDL-0071](https://app.notion.com/p/EDL-0071-Rebuild-To-n-Di-n-Tri-Th-c-Ch-nh-S-ch-Khi-ng-B-C-L-p-Tuy-t-i-T-i-Li-u-Nh-m-Chat-40c590f7e19e818aac0ec3ba7b2918ff) (Đã đồng bộ)



---

## EDL-0072: Định danh Webhook & Card Action Tuyệt đối Theo App ID — Deterministic Multi-Tenant Routing

**Status:** Approved
**Impact:** Critical
**Date:** 2026-11-03
**Context:** Giai đoạn sửa lỗi `Challenge code didn't get response` và thiết kế lại kiến trúc Multi-Tenant Webhook Routing cho HiLark Custom App.

### Problem Statement

Kiến trúc cũ dùng vòng lặp brute-force qua toàn bộ `lark_app_credentials` để thử giải mã:
1. **Bug ngắt sớm:** `lark_oapi` trả HTTP 500 (invalid PKCS7 padding) khi key sai; code cũ `return Response(...)` ngay lập tức tại candidate đầu tiên mà không kiểm tra `status_code == 200`, nên candidate thứ 2+ không bao giờ được thử.
2. **Vi phạm Zero-Trust:** Gói tin mã hóa của tenant B được thử giải mã bằng key của tenant A.
3. **Chicken-and-Egg trong Onboarding:** Bước cấu hình Webhook URL đặt trước bước nhập Key → Challenge không thể trả lời.

### Decision

**Chuyển sang Định danh Tuyệt đối 1-1 (Deterministic Routing):**

1. **Query-param route (khuyến nghị):** `POST /api/lark/events?app_id=cli_xxx` — `messenger.py` đọc `request.query_params.get("app_id")`, tra đúng 1 record, giải mã trực tiếp không loop.
2. **Path-based route (Phase 2):** `POST /api/lark/events/{app_id}` — `routers/lark.py` inject `app_id` vào `query_string` của Request object rồi forward sang `messenger.py`, tái dùng hoàn toàn logic hiện có.
3. **Card Action tương tự:** `POST /api/lark/card-action?app_id=` và `POST /api/lark/card-action/{app_id}`.
4. **OAuth Redirect URL giữ nguyên sạch** (`/setup/callback`), ngữ cảnh qua `state=setup_{task_id}`.
5. **Fallback loop giữ lại** (khi không có app_id param) nhưng đã vá bug: chỉ return khi `status_code == 200`.

### Alternatives Considered

- **Path-param thay toàn bộ query-param (rejected):** Lark Console không linh hoạt, nhiều khách dùng quen URL query.
- **Đặt app_id trong body/header Lark (rejected):** Lark không gửi `app_id` ở plaintext khi payload đã mã hóa.
- **Fallback pure (không có explicit app_id, rejected):** Vi phạm Zero-Trust, O(n) complexity, dễ vỡ khi nhiều tenant.

### Verification (bằng chứng thực tế — 2026-11-03)

- **Thủ công qua Ngrok (live):**
  - `POST https://hertz-liftoff-earphone.ngrok-free.dev/api/lark/events?app_id=cli_aa63f447fc78de27` → HTTP 200 `{"challenge":"live_test_challenge_external"}`
  - `POST https://hertz-liftoff-earphone.ngrok-free.dev/api/lark/events` (fallback) → HTTP 200 `{"challenge":"live_test_challenge_external_fallback"}`
- **Test suite:** `server/tests/lark/test_multitenant_webhook_routing.py` — 7 test cases covering:
  - Matching key (Test 1, 5)
  - Mismatched key cross-tenant rejection (Test 2)
  - Fallback by `updated_at` (Test 3)
  - Card action tenant routing (Test 4, 7)
  - Path-based parity with query-param (Test 6)

### Files Changed

| File | Thay đổi |
|---|---|
| `server/routers/lark.py` | Thêm 4 routes mới: `/events/{app_id}`, `/card-action/{app_id}` và hàm `_inject_app_id()` |
| `server/services/lark/messenger.py` | Direct lookup khi có `inbound_app_id`; fix bug fallback loop |
| `server/templates/setup_one_click.html` | Đảo thứ tự bước: Key trước (Step 3), Webhook URL sau (Step 5) |
| `server/templates/onboarding_wizard.html` | Tương tự setup_one_click; tự động sinh URL có `?app_id=cli_xxx` |
| `server/tests/lark/test_multitenant_webhook_routing.py` | Test suite 7 tests (mới tạo) |
| `docs/lark_event_subscription.md` | Cập nhật hướng dẫn dùng URL có `?app_id=` và path-based |
| `docs/IMPLEMENTATION_PLAN_APP_ID_WEBHOOK_ROUTING.md` | Plan gốc (đã tạo trong session trước) |

### Trade-offs

**Benefits:**
- O(1) lookup thay O(n) brute-force — không bao giờ thử key của tenant khác.
- Onboarding sequence hợp lý: Key vào trước → Webhook URL sau → Challenge pass ngay.
- Path-based hỗ trợ proxy doanh nghiệp cấm query string.

**Costs:**
- Lark Console cần cập nhật Request URL thủ công (thêm `?app_id=cli_xxx`) cho mỗi App.
- `_inject_app_id()` mutate `scope["query_string"]` — đây là internal Starlette API, cần chú ý khi upgrade Starlette.

### Related Decisions
- **EDL-0041:** Multi-Custom-App Registry foundation (`lark_app_service`, `runtime.py`).
- **EDL-0070:** TenantResourceResolver fail-closed — routing theo app_id phải match đúng tenant.
- **EDL-0035:** Zero Cross-Tenant Data Leakage.

---

## EDL-0073: Triệt tiêu Vòng lặp Đốt Token (Deduplication-First Policy Sync & Nâng Chu kỳ ChatScope Sync)

**Status:** Approved  
**Impact:** High  
**Date:** 2026-11-03  
**Context:** Khắc phục lỗi hệ thống tự động rebuild liên tục các tài liệu chính sách dù không có thay đổi nội dung, dẫn tới WeKnora gọi Gemini 2.5 Flash + BatchEmbed liên tục và đốt cạn token/credits của user.

### Problem Statement

1. **Policy Sync force=True:** Tại `bot_runner.py:393` (`_async_bitable_bootstrap()`) và `policy_sync.py:731` (`start_loop()`), `sync_policies` được gọi với cờ `force=True`. Cờ này bypass điều kiện kiểm tra MD5 hash trong `_upload_or_rebuild()`, dẫn đến việc tài liệu chính sách dù có hash khớp 100% với WeKnora vẫn bị xóa và nạp lại, kích hoạt pipeline embedding đa tầng.
2. **ChatScope Loop 30s:** Tại `bot_runner.py:420`, `scope_service.start_loop(interval_seconds=30)` chạy với chu kỳ 30 giây cực ngắn, đệ quy 4 tầng Lark Drive folder (4 GET requests/lần = 480 requests/giờ).

### Decision

1. **Deduplication-First Policy Sync:** Chuyển `force=True` thành `force=False` ở cả `bot_runner.py:393` và `policy_sync.py:731`. Hệ thống luôn so sánh MD5 hash giữa nội dung tài liệu Lark DocX/File với `file_hash` lưu trên WeKnora; nếu hash khớp thì giữ nguyên bản ghi hiện có, không xóa và không nạp lại. Cờ `force=True` chỉ được phép dùng khi người dùng chủ động bấm nút "Đồng bộ ngay" trên UI (qua router endpoint).
2. **Nâng chu kỳ ChatScope Sync:** Tăng `interval_seconds` từ 30s lên 1800s (30 phút) tại `bot_runner.py:424` để giảm thiểu tải Lark Drive API và loại bỏ hiện tượng gián đoạn worker.

### Verification (Bằng chứng thực tế)

- **Docker logs sau khi deploy & restart `hilark-server`:**
  - `ℹ️ [PolicySync] 'Lark DocX (WzxDw72ILiBI1Ika862jGWE9pta).md' không đổi nội dung (MD5 khớp). Giữ nguyên bản ghi WeKnora ba774ca3-9fde-4f3e-9353-8a57614c9394.`
  - `⏰ [ScopeSync Loop] Khởi động worker đồng bộ Chat Scopes định kỳ (Chu kỳ 1800s).`
  - Không còn bất kỳ request nạp WeKnora hoặc embed Gemini nào chạy nền ngoài ý muốn.
- **Test suite:** 29/29 tests pass (`server/tests/lark/`).

### Files Changed

| File | Thay đổi |
|---|---|
| `server/services/lark/bot_runner.py` | Line 393: `force=False`. Line 424: `interval_seconds=1800` |
| `server/services/knowledge/policy_sync.py` | Line 731: `force=False` trong `start_loop` |

---

## EDL-0074: Khắc Phục Triệt Để 4 Điểm Rò Rỉ Dữ Liệu Cross-Tenant & Cross-Group

**Status:** Approved  
**Impact:** Critical  
**Date:** 2026-11-03  
**Context:** Quét bảo mật toàn diện phát hiện 4 lỗ hổng rò rỉ dữ liệu tiềm ẩn giữa các tenant và nhóm chat trong quá trình nạp tài liệu, trích xuất thực thể/mệnh đề và đóng gói ngữ cảnh LLM.

### Problem Statement

1. **B3 - Context Composer Claim Leak:** Tại `context_composer.py:706`, điều kiện lọc `if not c.tenant_key or c.tenant_key == eff_tenant` chứa escape hatch cho phép các claim mồ côi (không gắn `tenant_key`) lọt vào bộ bối cảnh của bất kỳ tenant nào. Đồng thời tại `normalize_claims_data:379`, logic `tenant_key=f.get("tenant_key") or tenant_key` tự động gán tenant hiện tại cho bất kỳ claim nào bị thiếu tenant_key, làm mất tính cô lập.
2. **B1 - Document Handler Lark Doc Link Parser thiếu `tenant_key`:** Tại `document_handler.py:141-151`, khi người dùng chia sẻ liên kết Lark DocX, Wiki hoặc Folder, các hàm `parse_lark_docx`, `parse_lark_wiki`, `parse_lark_folder` được gọi mà không truyền `tenant_key=msg.tenant_key`, khiến Lark client dùng token mặc định hoặc token của tenant khác.
3. **B2 - Parse Attachment thiếu `tenant_key`:** `doc_parser.py:parse_attachment()` không nhận `tenant_key`, và gọi `self._lark.adownload_message_resource()` thông qua singleton `_lark` property, dẫn đến nguy cơ tải file đính kèm bằng sai bot token của tenant khác.
4. **B4 - Entity ID Collision & MongoDB Index Flaw:** `generate_stable_entity_id()` trong `llm_extractor.py:64` chỉ băm `uuid5(NAMESPACE_DNS, f"{clean_ws}:{clean_name}")` mà không có `tenant_key`. Hai tenant khác nhau có cùng tên thực thể (ví dụ: "Ban Giám Đốc", "Dự án Core") sẽ sinh ra trùng `ent_id`. Khi ghi vào MongoDB, collection `memories` có unique index chỉ trên `id` đơn lẻ (`idx_memories_id_unique`), dẫn tới `DuplicateKeyError` hoặc ghi đè thực thể của tenant khác.

### Decision

1. **Fix B3 (Strict Claim Isolation):**
   - Loại bỏ hoàn toàn escape hatch `not c.tenant_key` tại `context_composer.py:709`: Chỉ chấp nhận claim có `c.tenant_key == eff_tenant`.
   - Loại bỏ auto-adopting tại `normalize_claims_data:379`: Giữ nguyên `tenant_key=f.get("tenant_key")`.
2. **Fix B1 (Explicit Tenant Binding on Lark Parsers):**
   - Truyền tường minh `tenant_key=msg.tenant_key` vào `parse_lark_docx`, `parse_lark_wiki`, và `parse_lark_folder` trong `document_handler.py`.
3. **Fix B2 (Scoped Attachment Parser & Tenant Client Routing):**
   - Bổ sung `tenant_key: Optional[str] = None` vào `parse_attachment()` trong `doc_parser.py`.
   - Thêm helper `_get_lark_for_tenant(tenant_key)` trong `DocParserService` kết nối với `get_lark_service_for_tenant(tenant_key)` tại `runtime.py`.
   - Cập nhật caller tại `document_handler.py` truyền `tenant_key=msg.tenant_key`.
4. **Fix B4 (Deterministic Multi-Tenant Entity ID & Compound Index):**
   - Sửa `generate_stable_entity_id(workspace_id, name, tenant_key="")` băm seed `f"{clean_tenant}:{clean_ws}:{clean_name}"`.
   - Truyền `tenant_key` xuyên suốt: `chat_workflow.py` -> `extract_async` -> `extract_entities_async` -> `parse_entities` -> `generate_stable_entity_id`.
   - Cập nhật specification MongoDB Index trong `indexes.py`: Thay `idx_memories_id_unique` bằng compound unique index `[("tenant_key", ASCENDING), ("id", ASCENDING)]` (`idx_memories_tenant_id_unique`).
   - Thêm auto-migration drop index cũ trong `ensure_database_indexes()`.
   - Tạo migration script `scripts/migrate_entity_index.py` với chế độ dry-run và `--apply`.

### Verification (Bằng chứng thực tế)

- **Unit test suite mới:** `server/tests/final_test/test_data_leakage_fixes.py` (5/5 tests PASSED).
- **Multi-tenant isolation suite:** `server/tests/final_test/test_claims_knowledge_multi_tenant.py` (8/8 tests PASSED), `test_cross_tenant_isolation_complete.py` (5/5 tests PASSED).
- Tổng cộng 18/18 multi-tenant isolation tests pass 100%.

### Files Changed

| File | Thay đổi |
|---|---|
| `server/services/knowledge/context_composer.py` | Line 709: Strict filter `c.tenant_key == eff_tenant`. Line 379: Giữ nguyên `f.get("tenant_key")` |
| `server/services/knowledge/doc_parser.py` | Thêm `_get_lark_for_tenant()`, thêm param `tenant_key` vào `parse_attachment()` |
| `server/services/lark/handlers/document_handler.py` | Truyền `tenant_key=msg.tenant_key` vào 4 điểm gọi parser |
| `server/services/lark/runtime.py` | Thêm hàm `get_lark_service_for_tenant(tenant_key)` |
| `server/services/ai/llm_extractor.py` | Thêm `tenant_key` vào `generate_stable_entity_id`, `parse_entities`, `extract`, `extract_async` |
| `server/services/workflows/chat_workflow.py` | Truyền `tenant_key=eff_tenant` vào `extract_async()` trong `process_chat_message` và `process_document_for_claims` |
| `server/database/indexes.py` | Compound unique index `[("tenant_key", 1), ("id", 1)]` cho collection `memories`, drop index cũ |
| `scripts/migrate_entity_index.py` | Script migration & backfill an toàn cho MongoDB production |
| `server/tests/final_test/test_data_leakage_fixes.py` | Test suite 5 test cases bao phủ cả 4 bug |

---

## EDL-0075: Unified Fail-Closed BYOK, AI Config Manager tập trung, Mặc định `gemini-flash-latest` & JEV BYOK trên UI

**Status:** Approved  
**Impact:** Critical (Notion: High)  
**Date:** 2026-11-09  
**Context:** Thống nhất toàn bộ kiến trúc quản trị cấu hình AI/BYOK (LLM & JEV System 1), mặc định model Google Gemini về `gemini-flash-latest`, bổ sung dropdown Gemini `2.5` → `3.8` và cấu hình JEV BYOK trên UI với nguyên tắc Fail-Closed.

### Problem Statement

1. **Logic BYOK & Token phân mảnh:** Mã hóa/giải mã AES-256 Fernet và phân giải key rải rác giữa `user_settings_service.py`, `gemini_client.py`, `chat_workflow.py` và `chat_scopes.py`; chưa có RAM cache TTL + invalidation tập trung cho cấu hình AI/BYOK.
2. **Fallback ẩn vi phạm kỳ vọng BYOK:** Khi bật BYOK nhưng thiếu key, giải mã lỗi hoặc key bị từ chối, hệ thống có nguy cơ rơi về `chat_scope` key, `request_api_key`, System Key (`.env`), WeKnora Chat fallback hoặc `FAST_APPROVE_SET` (JEV) — gây tính phí nhầm hoặc che giấu lỗi cấu hình.
3. **Model mặc định lỗi thời & thiếu JEV BYOK trên UI:** Nhiều module vẫn gán cứng `gemini-2.5-flash`; chưa có danh mục dropdown Gemini `2.5` → `3.8`; JEV (`jev_classifier.py`) chỉ đọc `.env` dùng chung, không hỗ trợ BYOK theo tenant/user; chạy lại `OneClickSetupService` còn gọi `save_user_settings()` làm ghi đè mất BYOK.
4. **Telemetry & Dọn rác provider chưa nhất quán:** Đổi LLM provider hoặc xóa trống field trên UI có thể để lại `llm_base_url`/`llm_model` cũ; `cost_telemetry.py` thiếu metadata `tenant_key`, `provider`, `is_byok` đồng nhất cho cả LLM đa provider và JEV.

### Decision

**"Một đầu mối quản lý cấu hình AI (`AIConfigManager`) + Một danh mục model (`model_catalog`) + Hợp đồng Fail-Closed cho mọi nhánh BYOK."**

1. **Single Source of Truth Model Catalog (`server/services/ai/model_catalog.py`):**
   - Chuẩn hóa `DEFAULT_GEMINI_MODEL = "gemini-flash-latest"` (`google` -> `"gemini-flash-latest"`, `openai`/`chatgpt` -> `"gpt-4o-mini"`, `anthropic` -> `"claude-3-5-sonnet-20241022"`, `custom` -> `"gpt-3.5-turbo"`).
   - Cung cấp `GEMINI_MODEL_OPTIONS` từ `gemini-2.5-*` đến `gemini-3.8-flash` (+ `gemini-flash-latest`), cùng helper `normalize_provider()`, `is_gemini_3_or_newer()`, `is_gemini_25_pro()`.
2. **Centralized AI Config Manager (`server/services/ai/ai_config_manager.py`):**
   - Quản lý thống nhất AES-256 Fernet (`encrypt_key`, `decrypt_key`, `decrypt_key_strict`), masking, RAM cache TTL 60s + `invalidate(tenant_key, open_id)`, `resolve_ai_config()`, `resolve_llm_client()`, `resolve_llm_key()`, `resolve_jev_key()`, và `test_llm_connection()`.
   - Khi `save_config()`: đồng bộ `is_byok_enabled`/`llm_mode` và `is_jev_byok_enabled`/`jev_mode`, dọn rác `llm_base_url` và `llm_model` khi đổi provider hoặc truyền chuỗi rỗng từ UI, và tự động `invalidate()` cache.
   - `server/services/user_settings_service.py` giữ làm thin compatibility facade ủy quyền sang `ai_config_manager`.
3. **Hợp đồng Fail-Closed BYOK (`server/core/tenant_errors.py`, `gemini_client.py`, `jev_classifier.py`, `tenant_error_reply.py`):**
   - System Key (`.env`) **chỉ** được dùng khi `is_byok_enabled=False` / `is_jev_byok_enabled=False`.
   - Khi bật BYOK: thiếu key, giải mã lỗi, provider/JEV trả `401`/`403`/`400-auth`, hoặc toàn bộ model trả `400`/`404` -> ném `BYOKConfigurationError` (`error_code="byok_config_error"`, `http_status=400`, phản hồi chat tiếng Việt qua `BYOK_CONFIG_ERROR_REPLY`).
   - Loại bỏ các đường vòng ngoài hợp đồng: `chat_scope` key override, `request_api_key`, WeKnora Chat fallback trong `chat_workflow.py`, và `FAST_APPROVE_SET` fallback khi JEV BYOK bật.
4. **Hỗ trợ Đa thế hệ Gemini, Multi-Provider Usage & Telemetry (`gemini_client.py`, `jev_classifier.py`, `cost_telemetry.py`, `indexes.py`):**
   - `_apply_gemini_thinking_config`: Gemini `3.x+` dùng `thinkingConfig.thinkingLevel` (`low`/`medium`/`high`), `2.5 Pro` chỉ gửi `thinkingBudget` khi `> 0`, các dòng Flash còn lại gửi `thinkingBudget`.
   - JEV dùng `self._build_headers(api_key)` theo từng request (không mutate `self.headers` dùng chung) và bổ sung `ping_key()`.
   - Telemetry ghi nhận `provider`, `is_byok`, `tenant_key` (`last_llm_usage` & `last_jev_usage`), kèm index `[("tenant_key", 1), ("timestamp", -1)]` và `[("tenant_key", 1), ("updated_at", -1)]`.
5. **Callers, Setup Guard & UI (`chat_workflow.py`, `digest_workflow.py`, `doc_parser.py`, `chat_scopes.py`, `document_handler.py`, `member_message_handler.py`, `one_click_setup_service.py`, `routers/onboarding.py`, `onboarding_wizard.html`, `setup_one_click.html`):**
   - Các caller truyền `tenant_key` vào `ai_config_manager` / `jev_service` và re-raise `BYOKConfigurationError`.
   - `OneClickSetupService`: chỉ khởi tạo mặc định nếu chưa có `user_settings`; nếu đã có, chỉ cập nhật metadata, bảo toàn BYOK/JEV/Digest.
   - Bổ sung `GET /onboarding/api/models`, hỗ trợ `jev` trong `/onboarding/api/test-key`, trả HTTP 400 trên `BYOKConfigurationError` ở `/onboarding/api/save`; giao diện Wizard & One-Click Setup có dropdown Gemini `2.5` → `3.8` + `__custom__` và khu vực JEV BYOK + Test Key.

### Alternatives Considered

- **Giữ logic giải mã/cache trong `UserSettingsService` và sửa lẻ tẻ tại từng caller (rejected):** Khó đảm bảo tính nhất quán khi đồng thời có LLM BYOK và JEV BYOK, dễ tái phát fallback ngầm hoặc lệch cache giữa router và pipeline.
- **Im lặng fallback về System Key (`.env`) khi key BYOK của user hết hạn/sai (rejected):** Vi phạm kỳ vọng "chỉ dùng key hệ thống khi user không cấu hình", làm cháy quota hệ thống âm thầm thay vì báo cho quản trị viên.

### Verification (Bằng chứng thực tế — 2026-11-09)

- **Biên dịch cú pháp:** `cd server && python3 -m compileall -q core database decorators models routers services tests/final_test/test_ai_config_and_jev_byok.py tests/final_test/test_byok_onboarding.py` → **exit code 0**.
- **Test BYOK Onboarding (Step 6A):** `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests/final_test/test_byok_onboarding.py -v` → **33 passed**.
- **Test Unified AI Config & JEV BYOK (Step 6B):** `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests/final_test/test_ai_config_and_jev_byok.py -v` → **55 passed, 0 failed, 2 warnings in 2.86s**.
- **Full Regression Suite:** `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests -q` → **342 passed, 4 warnings in 7.02s** (DB local `LarkAssistant_test`).
- **Ranh giới chưa verify live:** Toàn bộ request HTTP ra Google Gemini, OpenAI, Anthropic và JEV trong các test đều được mock qua `httpx`; chưa chạy smoke test có phí trên API thật, MongoDB Atlas production, hay click E2E trực tiếp trong Lark Webview modal.

### Files Changed

| File | Thay đổi |
|---|---|
| `server/services/ai/model_catalog.py` | **(Mới)** `DEFAULT_GEMINI_MODEL = "gemini-flash-latest"`, catalog Gemini `2.5` → `3.8`, helper thế hệ model |
| `server/services/ai/ai_config_manager.py` | **(Mới)** `AIConfigManager`: AES-256 Fernet, cache TTL 60s + invalidate, dọn rác field, Fail-Closed resolver, connection ping |
| `server/services/user_settings_service.py` | Rút gọn thành thin compatibility facade ủy quyền `ai_config_manager` |
| `server/models/user_settings.py`, `server/models/onboarding.py` | Đồng bộ `llm_mode`/`is_byok_enabled` & `jev_mode`/`is_jev_byok_enabled`; payload JEV BYOK |
| `server/core/tenant_errors.py`, `server/services/lark/tenant_error_reply.py` | Thêm `BYOKConfigurationError` (HTTP 400) & phản hồi chat `BYOK_CONFIG_ERROR_REPLY` |
| `server/services/ai/gemini_client.py` | Mặc định `gemini-flash-latest`, `thinkingConfig` đa thế hệ, redact key, Fail-Closed BYOK, usage đa provider |
| `server/services/ai/jev_classifier.py` | Phân giải JEV BYOK qua `ai_config_manager`, Fail-Closed, per-request headers, `ping_key()` |
| `server/decorators/cost_telemetry.py`, `server/decorators/__init__.py` | `last_jev_usage`, tracking `provider` / `is_byok` / `tenant_key` |
| `server/database/indexes.py` | Thêm index `idx_telemetry_tenant_timestamp` & `idx_user_settings_tenant_updated` |
| `server/services/setup/one_click_setup_service.py` | Không ghi đè mất BYOK khi admin chạy lại One-Click Setup |
| `server/services/workflows/chat_workflow.py`, `digest_workflow.py`, `doc_parser.py`, `chat_scopes.py`, `document_handler.py`, `member_message_handler.py` | Phân giải qua `ai_config_manager` theo `tenant_key`, truyền `tenant_key` JEV, bỏ WeKnora fallback khi BYOK bật, re-raise `BYOKConfigurationError` |
| `server/routers/onboarding.py` | Thêm `GET /onboarding/api/models`, JEV trong `test-key`, trả HTTP 400 với `BYOKConfigurationError` |
| `server/templates/onboarding_wizard.html`, `server/templates/setup_one_click.html` | Dropdown Gemini `2.5` → `3.8` + `__custom__`, mục cấu hình & Test Key JEV BYOK |
| `server/tests/final_test/test_byok_onboarding.py`, `server/tests/final_test/test_ai_config_and_jev_byok.py` | Bộ kiểm thử Step 6A/6B (lưu ý `server/tests/` nằm trong `.gitignore`) |

### Trade-offs & Residual Risks

- **Cache TTL 60s trong RAM:** Tối ưu tốc độ đọc và tự `invalidate()` khi save qua UI/service, nhưng thay đổi thủ công trực tiếp trên MongoDB cần tối đa 60s để tự hết hạn trên instance đang chạy (và giả định 1 container/worker như ghi chú ở `EDL-0070`).
- **Tài liệu & UI hardcoded model:** Các model ngoài dropdown hoặc tên mới hơn (`custom` option `__custom__`) phụ thuộc endpoint Google API tại thời điểm chạy thật vì chưa kiểm thử live API call có phí.

### Notion

- Notion Page: [EDL-0075](https://app.notion.com/p/EDL-0075-Unified-Fail-Closed-BYOK-AI-Config-Manager-t-p-trung-M-c-nh-gemini-flash-latest-JEV--413590f7e19e814f8786ca5ca1b1c737) (Đã đồng bộ & xác minh)

### Related Decisions

- **Kế thừa hợp đồng Fail-Closed từ `EDL-0070`**
- **Supersede một phần `EDL-0017`** (thay 3-tier `chat_scope` / `request_api_key` fallback sang Fail-Closed qua `AIConfigManager`)
- **Supersede một phần `EDL-0019`** (cập nhật mặc định `gemini-flash-latest`, dropdown Gemini `2.5` → `3.8`, `thinkingLevel`, và bổ sung JEV BYOK)
- **Liên quan:** `EDL-0014` (Cost Telemetry), `EDL-0035` (Multi-Tenant Isolation)

---

## EDL-0076: Refactor LLMClient Đa Provider, Chuẩn Hóa Models & Schema MongoDB, Đưa Cost Telemetry Ra `.env` Và Đo `thinking_tokens`

**Status:** Approved  
**Impact:** Critical (Notion: High)  
**Date:** 2026-11-09  
**Context:** Kế thừa nền tảng `EDL-0075` để loại bỏ overfit tên/payload Gemini (`gemini_client.py`), gỡ logic `thinkingConfig` đoán mò theo regex tên model, đưa toàn bộ cấu trúc dữ liệu LLM & Telemetry về `server/models/`, làm sạch hoàn toàn schema Pydantic/MongoDB (`*_llm_*`, `output_tokens`, `thinking_tokens`), và chuyển toàn bộ bảng giá/tỷ giá telemetry ra `.env`.

### Problem Statement

1. **Overfit tên & payload Gemini trong `gemini_client.py`:** `_build_payload()` dựng cấu trúc kiểu Gemini rồi dịch ngược sang OpenAI/Anthropic; hàm `_apply_gemini_thinking_config()` kèm `is_gemini_3_or_newer` / `is_gemini_25_pro` và tham số `thinking_budget` ép cấu hình theo heuristic tên model dễ gãy khi model mới phát hành.
2. **Thiếu tập trung Data Models & Naming Schema lệch chuẩn provider-agnostic:** Các collection/model còn dùng tên cũ `encrypted_gemini_api_key`, `masked_gemini_api_key`, `raw_gemini_key`, `candidates_tokens`, `service="gemini"`, và chưa đo riêng `thinking_tokens` / `reasoning_tokens`.
3. **Chi phí & tỷ giá hardcoded:** Tỷ giá `USD_TO_VND_RATE`, `JEV_FLAT_COST_PER_REQUEST`, và giá từng model/provider gắn cứng trong Python, thậm chí từng áp sai giá Gemini Flash cho OpenAI/Anthropic.

### Decision

**"Provider-agnostic naming + Pure per-provider adapters + Models trong `server/models/` + `.env`-driven pricing & đo token thực tế."**

1. **Tập trung Models tại `server/models/` (`server/models/llm.py`, `server/models/telemetry.py`, `model_catalog.py`, `user_settings.py`, `onboarding.py`):**
   - Tạo `LLMModelOption`, frozen `LLMRequest` (với `@property is_multimodal`), `LLMUsage` (có `thinking_tokens` và `thinking_included_in_output`) trong `server/models/llm.py`.
   - Tạo `ModelPricing` (chấp nhận cả short keys `input`/`output`/`thinking` lẫn `*_per_1m_usd`, ràng buộc `>= 0`) và `TelemetryRecord` (`service="google"`, `output_tokens`, `thinking_tokens`) trong `server/models/telemetry.py`.
   - `GEMINI_MODEL_SPECS: List[LLMModelOption]` trong `model_catalog.py`; gỡ bỏ hoàn toàn `is_gemini_3_or_newer` và `is_gemini_25_pro`.
2. **Đổi tên & Tách Pure Adapters (`server/services/ai/llm_client.py`, xóa cứng `gemini_client.py`):**
   - Đổi `gemini_client.py` -> `llm_client.py` (`LLMClient`, `llm_client`), **xóa cứng** `gemini_client.py` cùng toàn bộ alias cũ (`GeminiClient`, `test_gemini_key`, `_call_gemini`, `calculate_gemini_cost`).
   - Tách 3 static pure payload builders nhận `(model, req: LLMRequest)`: `_build_google_payload`, `_build_openai_payload`, `_build_anthropic_payload`.
   - Gỡ bỏ `_apply_gemini_thinking_config` và tham số `thinking_budget` ở `LLMClient`, `digest_service`, `digest_workflow`; `@track_llm_cost` đo trực tiếp token trả về từ provider.
3. **Làm sạch Schema & Script Migration (`server/database/indexes.py`, `scripts/migrate_llm_schema.py`):**
   - Dùng trực tiếp `encrypted_llm_api_key`, `masked_llm_api_key`, `raw_llm_key`, `output_tokens`, `thinking_tokens`, `service="google"`, không giữ dual-write/legacy field trong runtime.
   - Bổ sung index `idx_telemetry_provider_model` `[("provider", 1), ("model", 1)]`.
   - Cung cấp `scripts/migrate_llm_schema.py` (`--dry-run` mặc định; `--apply` backfill, chuẩn hóa `service="gemini" -> "google"`, và mặc định `$unset` xóa field cũ trừ khi truyền `--keep-legacy`).
4. **Cấu hình Chi phí qua `.env` & Anti-Double-Counting (`server/core/config.py`, `.env.production.example`, `decorators/cost_telemetry.py`, `card_builder.py`):**
   - Đưa `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `USD_TO_VND_RATE`, `JEV_FLAT_COST_PER_REQUEST`, `LLM_DEFAULT_INPUT_COST_PER_1M_USD`, `LLM_DEFAULT_OUTPUT_COST_PER_1M_USD`, `LLM_DEFAULT_THINKING_COST_PER_1M_USD`, `LLM_PROVIDER_DEFAULT_PRICING_JSON`, `LLM_MODEL_PRICING_JSON` vào Settings/`.env` (có safe fallback khi JSON/float lỗi).
   - `calculate_llm_cost()` tra theo thứ tự ưu tiên: `"<provider>/<model>"` exact/longest-prefix -> `"<model>"` exact/longest-prefix -> `LLM_PROVIDER_DEFAULT_PRICING_JSON` -> `LLM_DEFAULT_*`. Chỉ cộng thêm `thinking_tokens` vào chi phí khi `thinking_included_in_output=False` (Google `thoughtsTokenCount`), tránh tính trùng `reasoning_tokens` / `thinking_tokens` đã nằm trong output của OpenAI / Anthropic.
   - `build_digest_approval_card()` gộp thống kê mọi LLM service khác `jev` với nhãn trung lập `LLM (...)` và chỉ hiển thị `, thinking: <n>` khi `> 0`.

### Alternatives Considered

- **Giữ shim chuyển tiếp `gemini_client.py` và fallback đọc field cũ vĩnh viễn trong runtime (rejected):** Gây nợ kỹ thuật kéo dài và dễ tái sinh code sử dụng nhầm alias/field cũ; theo yêu cầu làm sạch 100%, chuyển trách nhiệm làm sạch DB sang `scripts/migrate_llm_schema.py` (`--apply` có `$unset`).
- **Tự inject `thinkingConfig` bằng regex tên model (rejected):** Không ổn định qua các thế hệ model mới; bỏ hẳn để gửi payload tối giản chuẩn API mỗi provider và đo token thực tế.

### Verification (Bằng chứng thực tế — 2026-11-09)

- **Biên dịch cú pháp:** `python3 -m compileall -q server/core server/database server/decorators server/models server/routers server/services server/tests scripts` → **exit code 0**.
- **Quét ký hiệu cũ trong runtime `server/`:** Loại trừ `__pycache__`, `tests`, `docs`, `.venv`, `.pytest_cache` → **0 kết quả còn sót**; chỉ còn `scripts/migrate_llm_schema.py` và negative assertions / migration fixtures trong `server/tests`.
- **Test suites trọng tâm (4 file):** `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 /Users/hoainam/Desktop/HiLark/server/.venv/bin/python -m pytest tests/final_test/test_byok_onboarding.py tests/final_test/test_ai_config_and_jev_byok.py tests/final_test/phase_3_daily_digest_reporting/test_phase_3_daily_digest_reporting.py tests/lark/test_card_builder_schema.py -v` → **107 passed, 2 warnings in 2.76s**.
- **Full Regression Suite:** `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 /Users/hoainam/Desktop/HiLark/server/.venv/bin/python -m pytest tests -q` → **348 passed, 4 warnings in 7.21s** (DB local `LarkAssistant_test`).
- **Migration CLI & Unit Tests:** `scripts/migrate_llm_schema.py --help` exit 0; `--dry-run`, `--apply`, `--apply --keep-legacy` pass trên `FakeSyncDB`.
- **Phạm vi chưa verify live:** Các HTTP calls tới Google Gemini, OpenAI, Anthropic, JEV đều mock qua `httpx`; chưa chạy live paid API calls hay chạy `scripts/migrate_llm_schema.py --apply` trên MongoDB Atlas production.

### Files Changed (thuộc EDL-0076)

| File | Thay đổi |
|---|---|
| `server/models/llm.py`, `server/models/telemetry.py` | **(Mới)** `LLMModelOption`, frozen `LLMRequest`, `LLMUsage`, `ModelPricing`, `TelemetryRecord` |
| `server/services/ai/llm_client.py` | **(Mới, thay `gemini_client.py`)** `LLMClient` với 3 pure payload builders `_build_*_payload`, `_normalize_usage`, `@track_llm_cost`, Fail-Closed BYOK |
| `server/services/ai/gemini_client.py` | **(Đã xóa cứng)** Xóa bỏ cùng `GeminiClient`, `test_gemini_key`, `_call_gemini`, `calculate_gemini_cost` |
| `scripts/migrate_llm_schema.py` | **(Mới)** Migration script MongoDB `--dry-run` / `--apply` (`$unset` field cũ mặc định) / `--keep-legacy` |
| `server/core/config.py`, `.env.production.example` | Thêm `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, biến giá/tỷ giá `.env` + parser safe fallback |
| `server/models/__init__.py`, `user_settings.py`, `onboarding.py` | Re-export models mới; đổi field sang `*_llm_api_key`, `raw_llm_key` |
| `server/services/ai/model_catalog.py` | `GEMINI_MODEL_SPECS: List[LLMModelOption]`; gỡ `is_gemini_3_or_newer`, `is_gemini_25_pro` |
| `server/decorators/cost_telemetry.py`, `server/decorators/__init__.py`, `server/database/indexes.py` | `calculate_llm_cost`, `.env` pricing precedence, `thinking_tokens`, `service="google"`, index `idx_telemetry_provider_model` |
| `server/services/ai/ai_config_manager.py`, `server/services/user_settings_service.py` | Đồng bộ `raw_llm_key`, `*_llm_api_key`, `services.ai.llm_client`, xóa `test_gemini_key` |
| `server/services/{ai/__init__.py, __init__.py, ai_service.py, digest_service.py, ai/llm_extractor.py, knowledge/doc_parser.py, workflows/chat_workflow.py, workflows/digest_workflow.py, lark/card_builder.py}` | Cập nhật callers sang `llm_client` / `_call_llm` / `llm_vision_ocr`, bỏ `thinking_budget`, hiển thị card tổng hợp LLM + `thinking_tokens` |
| `server/routers/onboarding.py`, `server/templates/{onboarding_wizard.html, setup_one_click.html}` | `/api/test-key`, `/api/save`, `/api/settings` và UI chuyển hoàn toàn sang `raw_llm_key`, `masked_llm_api_key` |
| `server/tests/final_test/{test_byok_onboarding.py, test_ai_config_and_jev_byok.py, phase_3_daily_digest_reporting/test_phase_3_daily_digest_reporting.py}`, `server/tests/lark/test_card_builder_schema.py` | Cập nhật toàn bộ test theo hợp đồng mới + thêm `TestLLMModelsAndEnvPricingConfig`, `TestThinkingTokensAndCostCalculation`, `TestLLMSchemaMigrationScript`, test card multi-provider (lưu ý `server/tests/` nằm trong `.gitignore`) |

### Notion

- Notion Page: [EDL-0076](https://app.notion.com/p/EDL-0076-Refactor-LLMClient-a-provider-chu-n-h-a-Models-Schema-MongoDB-a-Cost-Telemetry-ra--413590f7e19e814cb219c7328239f002) (Đã đồng bộ & xác minh)

### Related Decisions

- **Cập nhật & mở rộng từ `EDL-0075`** (đổi `gemini_client.py` -> `llm_client.py`, đưa models về `server/models/`, gỡ heuristic `thinkingConfig`/`thinking_budget`, làm sạch schema MongoDB).
- **Supersede một phần `EDL-0014` & `EDL-0019`** (tách bảng giá đa provider/model sang `.env`, bỏ `calculate_gemini_cost`, đo `thinking_tokens` chống double-counting).

---

## EDL-0077: Hợp Nhất Token Broker & OAuth Gate Tuyến Tính, Phân Quyền Bot/User Token Fail-Closed, Mã Hóa `lark_auth` Và Gỡ Bỏ Hoàn Toàn Luồng ISV Store App

**Status:** Approved  
**Impact:** Critical (Notion: High)  
**Date:** 2026-11-10  
**Context:** Rà soát và tái cấu trúc toàn diện tầng xác thực (`server/services/auth/`), phân giải quyền Bot/User Token, cổng Onboarding tuyến tính, mã hóa token tại nghỉ trong `lark_auth`, vá 4 lỗ hổng DB isolation và gỡ bỏ hoàn toàn luồng ISV Store App để hệ thống vận hành nhất quán theo một mô hình duy nhất: **Custom App Multi-Tenant**.

### Problem Statement

1. **Quản lý Token phân tán & lệch Event Loop:** Dù đã có `TokenBroker` (`EDL-0070`), codebase vẫn tồn tại nhánh bypass trực tiếp sang `httpx` / `isv_token_service` tại `BaseProvisionService`, `_lock` & cache `_app_access_tokens` trùng lặp trong `LarkTokenService`, `_bg_delivery_executor` (`ThreadPoolExecutor` + `asyncio.run` làm rơi `ContextVar` tenant) trong `DraftService`, và nhánh `as_user=False` tại `LarkService` trả `RequestOption=None` thay vì lấy Bot Token qua broker.
2. **Tồn dư Single-Tenant & Fallback ẩn:** `LarkService`, `token_verifier`, `auth.py` và `onboarding.py` còn đọc/ghi `_id="primary_user_token"`, `self.user_access_token` trên singleton hoặc `.env`; `GET /auth/lark/status`, `POST /auth/lark/refresh`, `GET /onboarding/api/auth-status` thiếu `tenant_key` vẫn đọc nhầm token dùng chung; `/onboarding/api/save*` còn ghi đè `settings.LARK_*` toàn cục.
3. **Đảo ngược vai trò Bot Token vs User Token:** Nhiều luồng đọc dữ liệu workspace (`adownload_message_resource`, Contact `get_user_name`, `get_message`/`list_messages`, `DocX`/`Wiki`/`Drive`, `Bitable` `use_tenant_token=False` mặc định) dùng nhầm User Token của Sếp; ngược lại `areply_text(as_user=True)` và `reply_text(as_user=True)` khi thiếu User Token lại âm thầm fallback sang Bot Token để trả lời vào nhóm.
4. **Onboarding chưa tuyến tính & Bề mặt ISV dư thừa:** Chưa có cổng chặn `awaiting_user_oauth` khi doanh nghiệp mở app mà Admin chưa ủy quyền OAuth; tồn tại song song chế độ ISV Store App (`isv_token_service.py`, `IS_ISV_MODE`, `LARK_APP_TYPE`, `LARK_APP_TICKET`, `isv_auth`, `app_ticket` webhook, shared Store App fallback trong `tenant_resolver`) làm phình cấu hình và tạo nguy cơ fallback sai ngoài định hướng Custom App Multi-Tenant.
5. **Lộ plaintext token & 4 điểm rò rỉ DB:** Token OAuth lưu plaintext trong `lark_auth` và render nguyên văn trên HTML `/auth/lark/callback`; thiếu chặn `chat_scopes` rỗng `tenant_key`, `conversation_staging` thiếu `inject_tenant_filter`, `owner_command` thiếu `tenant_key`, và tra cứu admin theo `open_id` chưa fail-closed khi trùng giữa nhiều tenant.

### Decision

**"Một cổng `token_broker` + Một mô hình Custom App Multi-Tenant + Bot đọc tenant / User Fail-Closed khi phát ngôn đại diện Lãnh đạo + Mã hóa & cô lập tuyệt đối."**

1. **Phase 1 — Hợp nhất `token_broker` & Event-Loop Safety (`tenant_token_manager.py`, `token_service.py`, `base_provision_service.py`, `client.py`, `bitable.py`):**
   - Mọi yêu cầu `app` / `tenant` (Bot) / `user` token đi thống nhất qua `token_broker` (`TenantTokenManager` cache 3 chiều `(tenant_key, app_id, kind)` trên `core.token_loop`).
   - Gỡ bỏ `_lock` toàn cục và `_app_access_tokens` trong `LarkTokenService` (giữ lock lười theo cặp `(app_id, tenant_key)` `_get_refresh_lock` để bảo vệ Single-Use Refresh Token rotation); gỡ nhánh bypass `httpx` trong `BaseProvisionService`; chuẩn hóa `_get_request_option()` trong `client.py` và `LarkBaseService._get_headers(use_tenant_token=True)` đi qua broker.
2. **Phase 2 — Stateless Runtime, Xóa `primary_user_token` & Async Draft (`client.py`, `runtime.py`, `messenger.py`, `token_service.py`, `token_verifier.py`, `draft_workflow.py`, `routers/auth.py`, `routers/onboarding.py`):**
   - Xóa cứng `PRIMARY_TOKEN_DOC_ID`, `_cached_token_data`, `_sync_to_lark_client`, trường `user_access_token` dùng chung và mọi fallback `.env`.
   - Bắt buộc `tenant_key` (thiếu → `TenantContextMissing` HTTP 400) trên `GET /auth/lark/status`, `POST /auth/lark/refresh`, `GET /onboarding/api/auth-status`; `get_authorize_url()` bắt buộc có `app_id`.
   - Thay `DraftService._bg_delivery_executor` bằng `asyncio.create_task` giữ nguyên `async_tenant_context` và `ContextVar` runtime service (`set_current_lark_service`).
3. **Phase 3 — Phân quyền Bot Token vs User Token (`client.py`, `messenger.py`, `bitable.py`, `draft_workflow.py`, `card_builder.py`, `chat_workflow.py`, `doc_parser.py`):**
   - **Đọc dữ liệu tenant:** IM resources, Contact `get_user_name`, `get_message`/`list_messages` và `Bitable` (`use_tenant_token=True` mặc định) dùng **Bot Token** (`tenant_access_token`).
   - **Đọc tài liệu (`DocX`/`Wiki`/`Drive` async & sync):** Thử **Bot Token trước** (`tenant_access_token`), chỉ fallback có điều kiện sang User Token qua `_try_get_user_request_option()` khi Lark trả lỗi từ chối quyền (`_is_lark_permission_denied`), và nuốt `UserTokenMissing` để không sập luồng đọc chung.
   - **Phát ngôn đại diện Sếp (`as_user=True`):** `_prepare_user_msg_payload_async`, `areply_text`, `reply_text` tuyệt đối **Fail-Closed** với mã lỗi `user_token_missing` — `DraftService._send_claimed` hoàn bản nháp về `pending` và Bot tự động DM Lãnh đạo kèm thẻ `build_user_reauth_card`. Tách phân giải danh tính owner khỏi live User Token.
4. **Phase 4 — Onboarding Gate Tuyến Tính & Unified OAuth State (`tenant_state.py`, `tenant_lifecycle_handler.py`, `card_builder.py`, `routers/auth.py`, `routers/setup.py`, `routers/onboarding.py`, `one_click_setup_service.py`):**
   - Thêm trạng thái `AWAITING_USER_OAUTH = "awaiting_user_oauth"` (không nằm trong `SERVING_STATUSES = {READY}`) vào `tenant_state.py`.
   - Khi nhận `open_app` / `start_by_tenant` mà tenant chưa có Admin User Token, dừng ở `awaiting_user_oauth` và gửi Bot DM `build_admin_oauth_invite_card`; sau khi Admin hoàn tất OAuth tại `/auth/lark/callback`, tự động nối sang `provision_tenant_and_send_handover` (`PROVISIONING` → `READY` + thẻ bàn giao).
   - Hợp nhất OAuth state của `/setup/install` và `/setup/callback` sang `oauth_state_service` dùng 1 lần (`purpose="setup"`). Xóa ghi đè `settings.LARK_*` toàn cục ở `routers/onboarding.py` và điều hướng `/api/save-bot-config` qua `lark_app_service.register_app` + `link_tenant`.
5. **Phase 5 — Mã hóa Token Tại Nghỉ & Vá 4 Lỗ Hổng DB (`token_service.py`, `indexes.py`, `scoped_query.py`, `chat_scopes.py`, `member_message_handler.py`, `owner_command_handler.py`, `scripts/migrate_lark_auth_encryption.py`):**
   - Mã hóa AES-256 Fernet (`_encrypt_auth_secret` / `_decrypt_auth_secret`) cho `access_token` và `refresh_token` khi ghi vào `lark_auth`, hỗ trợ **dual-read** dữ liệu cũ để không gián đoạn khi rollout; che preview token trên HTML callback bằng `mask_token_preview`.
   - Bổ sung compound indexes trên `lark_auth` và script idempotent `scripts/migrate_lark_auth_encryption.py` (`--dry-run` mặc định; `--apply` mã hóa bản ghi plaintext và chuyển `primary_user_token` sang `archived_legacy_primary_user_token`).
   - Vá 4 điểm cô lập DB: giới hạn `chat_scopes` fallback theo `tenant_key` rỗng; `inject_tenant_filter` cho `conversation_staging` trong `member_message_handler.py`; truyền `tenant_key` trong `owner_command_handler.py` và `chat_workflow.py`; tách `resolve_tenant_by_admin_open_id` trong `scoped_query.py` (lọc `app_id`, fail-closed `None` nếu có `>= 2` tenant trùng `open_id`) dùng chung ở `messenger.py` và `routers/onboarding.py`.
6. **Gỡ bỏ hoàn toàn luồng ISV Store App — Chỉ vận hành Custom App Multi-Tenant:**
   - **Xóa cứng:** `server/services/auth/isv_token_service.py` và `server/tests/final_test/test_isv_token_service.py`.
   - Gỡ bỏ `IS_ISV_MODE`, `LARK_APP_TYPE`, `LARK_APP_TICKET`, `MONGO_ISV_AUTH_COLLECTION`, `get_isv_auth_collection()`, `ISVProvider`, nhánh webhook `app_ticket` trong `messenger.py`, fallback shared Store App trong `tenant_resolver.py`, `isv_auto_provision` / `build_isv_oauth_invite_card` (đổi sang `provisioned_by="auto_provision"` và `build_admin_oauth_invite_card`), cùng tài liệu/UI/models/scripts còn nhắc chế độ ISV.

### Alternatives Considered

- **Duy trì song song ISV Store App & Custom App Multi-Tenant (Rejected):** Kéo dài hai nhánh token/ticket/lookup đối nghịch và giữ đường fallback shared Store App khi toàn bộ vận hành thực tế dùng Custom App Multi-Tenant riêng cho từng doanh nghiệp.
- **Im lặng fallback sang Bot Token khi `areply_text(as_user=True)` thiếu User Token (Rejected):** Sai ngữ nghĩa đại diện phát ngôn của Sếp và che giấu lỗi hết hạn OAuth; chuyển sang Fail-Closed + hoàn `pending` + Bot DM thẻ ủy quyền lại.
- **Bỏ qua dual-read khi bật mã hóa `lark_auth` (Rejected):** Sẽ làm mất hiệu lực tức thì mọi `refresh_token` plaintext trước khi chạy migration; chọn Dual-read + Always-Encrypt Write + script migration idempotent.

### Verification (Bằng chứng thực tế — 2026-11-10)

- **Biên dịch bytecode:** `python3 -m compileall -q` trên `server/core`, `database`, `decorators`, `models`, `routers`, `services`, `tests` và `scripts` → **exit code 0**.
- **Quét ký hiệu cũ & ISV trong runtime `server/` và `scripts/`:** 0 tham chiếu code fallback còn sót tới `PRIMARY_TOKEN_DOC_ID`, `primary_user_token` (ngoài filter loại trừ `$ne` và script migrate), `_cached_token_data`, `_sync_to_lark_client`, `_bg_delivery_executor`, `IS_ISV_MODE`, `LARK_APP_TYPE`, `LARK_APP_TICKET`, `MONGO_ISV_AUTH_COLLECTION`, `get_isv_auth_collection`, `isv_token_service`, `ISVProvider`, `app_ticket`.
- **Migration CLI:** `scripts/migrate_lark_auth_encryption.py --help` → **exit code 0**; `--dry-run`, `--apply` và archive `primary_user_token` pass trên `FakeSyncDB` trong `test_phase5_encryption_and_isolation.py`.
- **Targeted pytest (auth, tenancy, lark, event ingress, marketplace onboarding, bitable provisioning):** **182 passed, 3 warnings in 5.62s**.
- **Full pytest suite:** `cd /Users/hoainam/Desktop/HiLark/server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 /Users/hoainam/Desktop/HiLark/server/.venv/bin/python -m pytest tests -q` → **374 passed, 3 warnings in 8.47s** (DB local `LarkAssistant_test`; đồng thời sửa 3 bug assertion/route cũ trong `test_oauth_login_flow_contract.py` và `test_phase5_encryption_and_isolation.py`).
- **Phạm vi chưa verify live (Scope Boundary):** Các lời gọi Lark OpenAPI & WeKnora trong pytest đều mock HTTP; **chưa** chạy `scripts/migrate_lark_auth_encryption.py --dry-run` / `--apply` trên MongoDB Atlas production, và **chưa** chạy kiểm thử E2E OAuth/Webhook trực tiếp với Lark Developer Console sau khi gỡ luồng ISV.

### Files Changed

- **Thay đổi trong Git working tree (nhánh `main`, chưa commit):** **49 file chỉnh sửa (`M`)**, **1 file xóa (`D`: `server/services/auth/isv_token_service.py`)**, **1 file mới (`??`: `scripts/migrate_lark_auth_encryption.py`)**.
- **Nhóm file chính:**
  - `server/services/auth/{__init__.py,tenant_token_manager.py,token_service.py,token_verifier.py}`, `server/services/auth_service.py`, xóa `server/services/auth/isv_token_service.py`
  - `server/services/tenancy/{tenant_resolver.py,tenant_state.py}`, `server/services/lark_app_service.py`
  - `server/services/lark/{base_provision_service.py,bitable.py,card_builder.py,client.py,dispatcher.py,messenger.py,runtime.py}` & `handlers/{card_action_handler.py,document_handler.py,member_message_handler.py,owner_command_handler.py,tenant_lifecycle_handler.py}`
  - `server/services/workflows/{chat_workflow.py,draft_workflow.py}`, `server/services/knowledge/{chat_scopes.py,doc_parser.py}`, `server/services/setup/one_click_setup_service.py`
  - `server/database/{db.py,indexes.py,scoped_query.py}`, `server/core/config.py`, `.env.production.example` (`.gitignore`), `server/models/{chat.py,chat_queue.py,chat_scope.py,digest.py,lark.py,memory.py,onboarding.py,tenant.py,user_settings.py}`
  - `server/routers/{auth.py,digest.py,onboarding.py,policy.py,scope.py,setup.py}`, `server/templates/{onboarding_wizard.html,setup_one_click.html}`
  - `scripts/{audit_tenant_config_readonly.py,migrate_lark_auth_encryption.py}`, `README.md`, `server/docs/README.md`
  - `server/tests/` (`.gitignore`): bổ sung `tests/lark/test_phase3_bot_reads_and_fail_closed_im.py`, `tests/auth/test_phase5_encryption_and_isolation.py`, xóa `tests/final_test/test_isv_token_service.py` và cập nhật các suite `auth/`, `tenancy/`, `lark/`, `final_test/`.

### Trade-offs & Residual Risks

- **Dual-read tạm thời trên `lark_auth`:** Trong giai đoạn chuyển tiếp trước khi chạy `scripts/migrate_lark_auth_encryption.py --apply` trên production, hàm giải mã vẫn đọc được bản ghi plaintext cũ nếu chưa phải token Fernet (hoặc khi khóa giải mã không khớp format `gAAAA...`), nên cần chạy `--apply` càng sớm càng tốt khi triển khai để khóa chặt tại nghỉ.
- **Một Custom App cho mỗi doanh nghiệp:** Vì đã gỡ bỏ hoàn toàn ISV Store App (`app_ticket` / shared App), mọi doanh nghiệp onboard mới bắt buộc đăng ký bộ khóa Custom App (`app_id`, `app_secret`, webhook URL `?app_id=...`) qua `/setup` hoặc `/onboarding/wizard`.

### Notion

- Notion Page: [EDL-0077](https://app.notion.com/p/EDL-0077-H-p-nh-t-Token-Broker-OAuth-Gate-tuy-n-t-nh-ph-n-quy-n-Bot-User-Token-Fail-Closed-m-h-414590f7e19e8159aea0e9a7ea0174c1) (`414590f7-e19e-8159-aea0-e9a7ea0174c1` — Đã đồng bộ & xác minh đọc lại).

### Related Decisions

- **Kế thừa & hoàn thiện `EDL-0070`** (TokenBroker 3 chiều, `TenantResourceResolver` fail-closed, `oauth_states` dùng 1 lần, gỡ fallback `.env`), **`EDL-0072`** (Webhook App ID routing), **`EDL-0074`** (Cross-Tenant Data Isolation).
- **Supersede một phần `EDL-0020`, `EDL-0022`, `EDL-0026`, `EDL-0028`, `EDL-0039`** (loại bỏ hoàn toàn kiến trúc ISV Store App / `app_ticket` / `isv_auth` / `isv_token_service` / Dual-mode UI; chuẩn hóa về Custom App Multi-Tenant + cổng `awaiting_user_oauth`).

