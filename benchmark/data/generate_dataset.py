"""
Deterministic dataset generator for the benchmark.

Generates a rich organizational dataset with entities, relationships,
messages, documents, meetings, and decisions — all interconnected to
support single-hop through multi-hop queries.

Uses Faker with a fixed seed for reproducibility.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from faker import Faker

from benchmark.models import (
    BenchmarkQuestion,
    CampaignEntity,
    CustomerEntity,
    Dataset,
    DecisionEntity,
    DepartmentEntity,
    DocumentEntity,
    Entity,
    EntityType,
    IssueEntity,
    MeetingEntity,
    MessageEntity,
    ProjectEntity,
    QuestionDifficulty,
    Relationship,
    RelationshipType,
    TaskEntity,
    TeamEntity,
    UserEntity,
)

# Vietnamese names for realism
VN_FIRST_NAMES = [
    "An", "Bình", "Cường", "Dũng", "Đức", "Giang", "Hải", "Hùng",
    "Khánh", "Linh", "Minh", "Nam", "Phong", "Quân", "Sơn", "Thành",
    "Trung", "Tuấn", "Việt", "Xuân", "Anh", "Chi", "Hà", "Hương",
    "Lan", "Mai", "Ngọc", "Phương", "Thanh", "Thảo", "Thu", "Trang",
    "Vân", "Yến", "Đạt", "Hoàng", "Long", "Nghĩa", "Tâm", "Toàn",
]
VN_LAST_NAMES = [
    "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan",
    "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương",
]

DEPARTMENTS = [
    ("dept_01", "Marketing", "Handles all marketing campaigns and brand strategy"),
    ("dept_02", "Engineering", "Builds and maintains all technical products"),
    ("dept_03", "Sales", "Manages customer relationships and revenue"),
    ("dept_04", "Product", "Defines product vision and roadmap"),
    ("dept_05", "Operations", "Handles internal processes and logistics"),
    ("dept_06", "HR", "People management and talent acquisition"),
    ("dept_07", "Finance", "Financial planning and accounting"),
]

TEAM_TEMPLATES = [
    # (team_id, name, dept_id, focus)
    ("team_01", "Marketing Strategy", "dept_01", "Brand and campaign strategy"),
    ("team_02", "Digital Marketing", "dept_01", "Online campaigns and SEO"),
    ("team_03", "Content Team", "dept_01", "Content creation and copywriting"),
    ("team_04", "Backend Engineering", "dept_02", "Server-side development"),
    ("team_05", "Frontend Engineering", "dept_02", "UI/UX development"),
    ("team_06", "DevOps", "dept_02", "Infrastructure and deployment"),
    ("team_07", "QA Team", "dept_02", "Quality assurance and testing"),
    ("team_08", "Enterprise Sales", "dept_03", "Large account management"),
    ("team_09", "SMB Sales", "dept_03", "Small/medium business sales"),
    ("team_10", "Product Core", "dept_04", "Core product features"),
    ("team_11", "Product Growth", "dept_04", "Growth and user acquisition features"),
    ("team_12", "Logistics", "dept_05", "Supply chain and delivery"),
    ("team_13", "Talent Acquisition", "dept_06", "Recruiting and hiring"),
]

CUSTOMER_TEMPLATES = [
    ("cust_01", "TechViet Corp", "Technology", "Enterprise"),
    ("cust_02", "SaigonFood JSC", "F&B", "Enterprise"),
    ("cust_03", "GreenEnergy VN", "Energy", "Premium"),
    ("cust_04", "EduSmart Academy", "Education", "Standard"),
    ("cust_05", "MediCare Plus", "Healthcare", "Enterprise"),
    ("cust_06", "FinanceHub VN", "Finance", "Premium"),
    ("cust_07", "RetailMax", "Retail", "Standard"),
    ("cust_08", "LogiTrans VN", "Logistics", "Standard"),
    ("cust_09", "BuildPro Construction", "Construction", "Premium"),
    ("cust_10", "MediaWave", "Media", "Standard"),
    ("cust_11", "AgroTech Solutions", "Agriculture", "Standard"),
    ("cust_12", "CyberSecure VN", "Security", "Premium"),
]

PROJECT_TEMPLATES = [
    ("proj_01", "Project Alpha", "team_01", "cust_01", "active", "high"),
    ("proj_02", "Project Alpha 2", "team_01", "cust_01", "planning", "medium"),
    ("proj_03", "Project Beta", "team_04", "cust_02", "active", "high"),
    ("proj_04", "Project Gamma", "team_05", "cust_03", "active", "medium"),
    ("proj_05", "Project Delta", "team_08", "cust_04", "completed", "low"),
    ("proj_06", "Project Epsilon", "team_10", "cust_05", "active", "critical"),
    ("proj_07", "Project Zeta", "team_02", "cust_06", "active", "high"),
    ("proj_08", "Project Eta", "team_04", "cust_07", "delayed", "high"),
    ("proj_09", "Project Theta", "team_06", "cust_08", "active", "medium"),
    ("proj_10", "Project Iota", "team_09", "cust_09", "active", "medium"),
    ("proj_11", "Project Kappa", "team_07", "cust_10", "delayed", "high"),
    ("proj_12", "Project Lambda", "team_11", "cust_11", "planning", "low"),
    ("proj_13", "Project Mu", "team_03", "cust_12", "active", "high"),
    ("proj_14", "Project Nu", "team_12", "cust_02", "active", "medium"),
    ("proj_15", "Project Xi", "team_10", "cust_01", "active", "high"),
    ("proj_16", "Project Omicron", "team_01", "cust_03", "delayed", "critical"),
    ("proj_17", "Project Pi", "team_04", "cust_06", "active", "medium"),
    ("proj_18", "Project Rho", "team_08", "cust_05", "active", "high"),
    ("proj_19", "Project Sigma", "team_05", "cust_09", "completed", "low"),
    ("proj_20", "Project Tau", "team_02", "cust_10", "active", "medium"),
]

ISSUE_SEVERITIES = ["critical", "high", "medium", "low"]
ISSUE_STATUSES = ["open", "in_progress", "resolved", "closed"]
TASK_STATUSES = ["todo", "in_progress", "review", "done", "blocked"]
TASK_PRIORITIES = ["critical", "high", "medium", "low"]
CAMPAIGN_TYPES = ["social_media", "email", "content", "paid_ads", "event", "partnership"]

BASE_DATE = datetime(2026, 8, 1)


class DatasetGenerator:
    """Generates a complete benchmark dataset with ground truth."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.fake = Faker("vi_VN")
        self.fake.seed_instance(seed)
        Faker.seed(seed)

        self.entities: list[Entity] = []
        self.relationships: list[Relationship] = []
        self._entity_map: dict[str, Entity] = {}

        # Quick-access indices
        self._users: list[UserEntity] = []
        self._teams: list[TeamEntity] = []
        self._projects: list[ProjectEntity] = []
        self._customers: list[CustomerEntity] = []
        self._tasks: list[TaskEntity] = []
        self._meetings: list[MeetingEntity] = []
        self._messages: list[MessageEntity] = []
        self._documents: list[DocumentEntity] = []
        self._issues: list[IssueEntity] = []
        self._decisions: list[DecisionEntity] = []
        self._campaigns: list[CampaignEntity] = []
        self._departments: list[DepartmentEntity] = []

        # Relationship lookup
        self._user_team: dict[str, str] = {}  # user_id -> team_id
        self._team_dept: dict[str, str] = {}  # team_id -> dept_id
        self._team_projects: dict[str, list[str]] = {}  # team_id -> [proj_id]
        self._project_customer: dict[str, str] = {}  # proj_id -> cust_id
        self._project_issues: dict[str, list[str]] = {}
        self._project_tasks: dict[str, list[str]] = {}
        self._project_meetings: dict[str, list[str]] = {}
        self._meeting_decisions: dict[str, list[str]] = {}
        self._decision_campaigns: dict[str, list[str]] = {}
        self._issue_meetings: dict[str, list[str]] = {}
        self._message_project: dict[str, str] = {}
        self._task_user: dict[str, str] = {}

    def _add_entity(self, entity: Entity):
        self.entities.append(entity)
        self._entity_map[entity.id] = entity

    def _add_rel(self, src: str, tgt: str, rtype: RelationshipType, **attrs: Any):
        self.relationships.append(Relationship(
            source_id=src,
            target_id=tgt,
            type=rtype,
            attributes=attrs,
            created_at=BASE_DATE,
        ))

    # ------------------------------------------------------------------
    # Entity generators
    # ------------------------------------------------------------------
    def _generate_users(self, count: int = 40):
        used_names: set[str] = set()
        for i in range(1, count + 1):
            while True:
                first = self.rng.choice(VN_FIRST_NAMES)
                last = self.rng.choice(VN_LAST_NAMES)
                full = f"{last} {first}"
                if full not in used_names:
                    used_names.add(full)
                    break
            uid = f"user_{i:03d}"
            roles = ["engineer", "designer", "manager", "lead", "analyst",
                      "coordinator", "specialist", "director", "intern"]
            role = self.rng.choice(roles)
            u = UserEntity(
                id=uid, name=full,
                email=f"{first.lower()}.{last.lower()}@company.vn",
                role=role,
                created_at=BASE_DATE - timedelta(days=self.rng.randint(30, 365)),
            )
            self._add_entity(u)
            self._users.append(u)

    def _generate_departments(self):
        for did, name, desc in DEPARTMENTS:
            d = DepartmentEntity(
                id=did, name=name, description=desc,
                created_at=BASE_DATE - timedelta(days=365),
            )
            self._add_entity(d)
            self._departments.append(d)

    def _generate_teams(self):
        for tid, name, dept_id, focus in TEAM_TEMPLATES:
            t = TeamEntity(
                id=tid, name=name, focus_area=focus,
                created_at=BASE_DATE - timedelta(days=300),
            )
            self._add_entity(t)
            self._teams.append(t)
            self._add_rel(tid, dept_id, RelationshipType.BELONGS_TO)
            self._team_dept[tid] = dept_id
            self._team_projects[tid] = []

    def _assign_users_to_teams(self):
        # Ensure each team gets at least 2 members
        team_ids = [t.id for t in self._teams]
        user_list = list(self._users)
        self.rng.shuffle(user_list)

        # First pass: 2 per team
        idx = 0
        for tid in team_ids:
            for _ in range(2):
                if idx < len(user_list):
                    self._user_team[user_list[idx].id] = tid
                    self._add_rel(user_list[idx].id, tid, RelationshipType.MEMBER_OF)
                    idx += 1

        # Remaining users distributed randomly
        for u in user_list[idx:]:
            tid = self.rng.choice(team_ids)
            self._user_team[u.id] = tid
            self._add_rel(u.id, tid, RelationshipType.MEMBER_OF)

    def _generate_customers(self):
        for cid, name, industry, tier in CUSTOMER_TEMPLATES:
            c = CustomerEntity(
                id=cid, name=name, industry=industry, tier=tier,
                created_at=BASE_DATE - timedelta(days=self.rng.randint(60, 500)),
            )
            self._add_entity(c)
            self._customers.append(c)

    def _generate_projects(self):
        for pid, name, team_id, cust_id, status, priority in PROJECT_TEMPLATES:
            start = BASE_DATE + timedelta(days=self.rng.randint(-60, -10))
            deadline = start + timedelta(days=self.rng.randint(30, 120))
            p = ProjectEntity(
                id=pid, name=name, status=status, priority=priority,
                start_date=start, deadline=deadline,
                created_at=start,
            )
            self._add_entity(p)
            self._projects.append(p)
            self._add_rel(team_id, pid, RelationshipType.RESPONSIBLE_FOR)
            self._add_rel(team_id, cust_id, RelationshipType.WORKS_WITH)
            self._team_projects.setdefault(team_id, []).append(pid)
            self._project_customer[pid] = cust_id
            self._project_issues[pid] = []
            self._project_tasks[pid] = []
            self._project_meetings[pid] = []

    def _generate_issues(self, count: int = 80):
        proj_ids = [p.id for p in self._projects]
        for i in range(1, count + 1):
            iid = f"issue_{i:03d}"
            pid = self.rng.choice(proj_ids)
            reporter = self.rng.choice(self._users)
            reported = BASE_DATE + timedelta(days=self.rng.randint(-30, 45))
            severity = self.rng.choice(ISSUE_SEVERITIES)
            status = self.rng.choice(ISSUE_STATUSES)
            resolved = reported + timedelta(days=self.rng.randint(1, 30)) if status in ("resolved", "closed") else None

            proj = self._entity_map[pid]
            cust_id = self._project_customer.get(pid)
            cust_name = self._entity_map[cust_id].name if cust_id else "internal"

            issue_descriptions = [
                f"Performance degradation in {proj.name} integration module affecting {cust_name}",
                f"Data sync failure between {proj.name} and {cust_name} systems",
                f"UI rendering issue in {proj.name} dashboard for {cust_name}",
                f"API timeout when processing {cust_name} requests in {proj.name}",
                f"Security vulnerability found in {proj.name} authentication flow",
                f"Missing validation in {proj.name} for {cust_name} input data",
                f"Memory leak in {proj.name} background worker",
                f"Incorrect calculation in {proj.name} billing module for {cust_name}",
                f"Broken pagination in {proj.name} report generation",
                f"Race condition in {proj.name} order processing for {cust_name}",
            ]

            iss = IssueEntity(
                id=iid, name=f"Issue #{i}",
                severity=severity, status=status,
                description=self.rng.choice(issue_descriptions),
                reported_date=reported,
                resolved_date=resolved,
                created_at=reported,
            )
            self._add_entity(iss)
            self._issues.append(iss)
            self._add_rel(pid, iid, RelationshipType.HAS_ISSUE)
            self._add_rel(iid, reporter.id, RelationshipType.REPORTED_BY)
            self._project_issues[pid].append(iid)

        # Add some blocking relationships between issues
        for _ in range(15):
            a, b = self.rng.sample(self._issues, 2)
            self._add_rel(a.id, b.id, RelationshipType.BLOCKS)

    def _generate_tasks(self, count: int = 150):
        proj_ids = [p.id for p in self._projects]
        user_ids = [u.id for u in self._users]
        for i in range(1, count + 1):
            tid = f"task_{i:03d}"
            pid = self.rng.choice(proj_ids)
            assignee = self.rng.choice(user_ids)
            status = self.rng.choice(TASK_STATUSES)
            priority = self.rng.choice(TASK_PRIORITIES)
            due = BASE_DATE + timedelta(days=self.rng.randint(1, 60))
            proj = self._entity_map[pid]
            task_names = [
                f"Implement {proj.name} API endpoint",
                f"Write unit tests for {proj.name}",
                f"Design UI mockup for {proj.name}",
                f"Review {proj.name} architecture",
                f"Deploy {proj.name} staging environment",
                f"Optimize {proj.name} database queries",
                f"Fix bug in {proj.name} authentication",
                f"Update {proj.name} documentation",
                f"Conduct code review for {proj.name}",
                f"Set up CI/CD for {proj.name}",
            ]
            t = TaskEntity(
                id=tid, name=self.rng.choice(task_names),
                status=status, priority=priority, due_date=due,
                created_at=BASE_DATE + timedelta(days=self.rng.randint(-20, 10)),
            )
            self._add_entity(t)
            self._tasks.append(t)
            self._add_rel(pid, tid, RelationshipType.HAS_TASK)
            self._add_rel(tid, assignee, RelationshipType.ASSIGNED_TO)
            self._project_tasks[pid].append(tid)
            self._task_user[tid] = assignee

            # Some tasks related to issues
            if self.rng.random() < 0.3 and self._project_issues.get(pid):
                issue_id = self.rng.choice(self._project_issues[pid])
                self._add_rel(tid, issue_id, RelationshipType.RELATED_TO)

    def _generate_meetings(self, count: int = 70):
        proj_ids = [p.id for p in self._projects]
        for i in range(1, count + 1):
            mid = f"meeting_{i:03d}"
            pid = self.rng.choice(proj_ids)
            proj = self._entity_map[pid]
            date = BASE_DATE + timedelta(days=self.rng.randint(-30, 50))
            dur = self.rng.choice([30, 45, 60, 90])

            # Pick attendees from the team responsible for the project
            team_id = None
            for r in self.relationships:
                if r.target_id == pid and r.type == RelationshipType.RESPONSIBLE_FOR:
                    team_id = r.source_id
                    break
            attendees = [u for u in self._users if self._user_team.get(u.id) == team_id]
            if len(attendees) < 2:
                attendees = self.rng.sample(self._users, min(4, len(self._users)))
            else:
                attendees = self.rng.sample(attendees, min(len(attendees), self.rng.randint(2, 5)))

            # Some meetings discuss issues
            discussed_issues = []
            if self._project_issues.get(pid) and self.rng.random() < 0.6:
                n = min(len(self._project_issues[pid]), self.rng.randint(1, 3))
                discussed_issues = self.rng.sample(self._project_issues[pid], n)

            summary_parts = [f"Cuộc họp về {proj.name}"]
            if discussed_issues:
                issue_names = [self._entity_map[iid].name for iid in discussed_issues]
                summary_parts.append(f"Thảo luận về {', '.join(issue_names)}")
            summary_parts.append(f"Ngày {date.strftime('%d/%m/%Y')}")

            agenda_parts = [f"1. Cập nhật tiến độ {proj.name}"]
            if discussed_issues:
                agenda_parts.append(f"2. Xử lý vấn đề: {', '.join([self._entity_map[x].name for x in discussed_issues])}")
            agenda_parts.append(f"{len(agenda_parts)+1}. Kế hoạch tuần tiếp theo")

            m = MeetingEntity(
                id=mid, name=f"Họp {proj.name} - {date.strftime('%d/%m')}",
                date=date, duration_minutes=dur,
                summary=". ".join(summary_parts),
                agenda="\n".join(agenda_parts),
                created_at=date,
            )
            self._add_entity(m)
            self._meetings.append(m)
            self._add_rel(pid, mid, RelationshipType.HAS_MEETING)
            self._add_rel(mid, pid, RelationshipType.DISCUSSES)
            self._project_meetings[pid].append(mid)

            for att in attendees:
                self._add_rel(mid, att.id, RelationshipType.INVOLVES)

            for iid in discussed_issues:
                self._add_rel(mid, iid, RelationshipType.DISCUSSES)
                self._issue_meetings.setdefault(iid, []).append(mid)

    def _generate_decisions(self, count: int = 40):
        meetings_with_issues = [
            m for m in self._meetings
            if any(r.source_id == m.id and r.type == RelationshipType.DISCUSSES
                   and r.target_id.startswith("issue_") for r in self.relationships)
        ]
        available = meetings_with_issues if meetings_with_issues else self._meetings

        for i in range(1, count + 1):
            did = f"decision_{i:03d}"
            meeting = self.rng.choice(available)
            mid = meeting.id

            # Find the project discussed
            pid = None
            for r in self.relationships:
                if r.source_id == mid and r.type == RelationshipType.DISCUSSES:
                    if r.target_id.startswith("proj_"):
                        pid = r.target_id
                        break
            if not pid:
                pid = self.rng.choice([p.id for p in self._projects])

            proj = self._entity_map[pid]
            decision_templates = [
                f"Quyết định tăng thêm 2 nhân sự cho {proj.name}",
                f"Quyết định thay đổi deadline của {proj.name} sang cuối tháng 10",
                f"Quyết định chuyển {proj.name} sang công nghệ mới",
                f"Quyết định tạm dừng feature X của {proj.name} để ưu tiên bug fix",
                f"Quyết định mở rộng scope của {proj.name} theo yêu cầu khách hàng",
                f"Quyết định triển khai hotfix cho {proj.name}",
                f"Quyết định thay đổi chiến lược tiếp cận cho {proj.name}",
                f"Quyết định nâng cấp infrastructure cho {proj.name}",
                f"Quyết định cắt giảm tính năng {proj.name} để đúng deadline",
                f"Quyết định hợp tác với đối tác mới cho {proj.name}",
            ]
            rationale_templates = [
                "Do phát hiện nhiều issue critical cần xử lý gấp",
                "Dựa trên phản hồi của khách hàng về performance",
                "Cần tối ưu resource để đảm bảo timeline",
                "Thị trường đang thay đổi, cần adapt nhanh",
                "Team đã overload, cần phân bổ lại công việc",
                "Phân tích cost-benefit cho thấy cần thay đổi approach",
            ]

            d = DecisionEntity(
                id=did, name=f"Decision #{i}",
                description=self.rng.choice(decision_templates),
                rationale=self.rng.choice(rationale_templates),
                status=self.rng.choice(["approved", "pending", "implemented"]),
                date=meeting.date,
                created_at=meeting.date,
            )
            self._add_entity(d)
            self._decisions.append(d)
            self._add_rel(mid, did, RelationshipType.RESULTS_IN)
            self._add_rel(did, pid, RelationshipType.AFFECTS)
            self._meeting_decisions.setdefault(mid, []).append(did)

            # Some decisions create tasks
            if self.rng.random() < 0.4 and self._project_tasks.get(pid):
                task_id = self.rng.choice(self._project_tasks[pid])
                self._add_rel(mid, task_id, RelationshipType.CREATES)

    def _generate_campaigns(self, count: int = 25):
        for i in range(1, count + 1):
            cid = f"campaign_{i:03d}"
            proj = self.rng.choice(self._projects)
            cust = self._entity_map.get(self._project_customer.get(proj.id))
            start = BASE_DATE + timedelta(days=self.rng.randint(-30, 30))
            end = start + timedelta(days=self.rng.randint(14, 90))
            budget = self.rng.randint(5, 50) * 1000000  # VND

            quarter = f"Q{((start.month - 1) // 3) + 1}"
            cust_suffix = f" - {cust.name}" if cust and self.rng.random() < 0.4 else ""

            # Create distractor-prone naming
            name_templates = [
                f"Campaign {quarter}{cust_suffix}",
                f"Campaign {quarter} - {proj.name}",
                f"Campaign {proj.name} {quarter}",
            ]

            c = CampaignEntity(
                id=cid, name=self.rng.choice(name_templates),
                campaign_type=self.rng.choice(CAMPAIGN_TYPES),
                status=self.rng.choice(["draft", "active", "paused", "completed", "delayed"]),
                budget=budget,
                start_date=start,
                end_date=end,
                target_audience=cust.industry if cust else "General",
                created_at=start - timedelta(days=7),
            )
            self._add_entity(c)
            self._campaigns.append(c)
            self._add_rel(cid, proj.id, RelationshipType.TARGETS)

            # Link some decisions to campaigns
            if self._meeting_decisions:
                for mid, dids in self._meeting_decisions.items():
                    for did in dids:
                        dec = self._entity_map[did]
                        if hasattr(dec, 'description') and proj.name in dec.description:
                            if self.rng.random() < 0.3:
                                self._add_rel(did, cid, RelationshipType.CHANGES)
                                self._decision_campaigns.setdefault(did, []).append(cid)

    def _generate_documents(self, count: int = 70):
        proj_ids = [p.id for p in self._projects]
        doc_types = ["specification", "report", "proposal", "analysis",
                     "review", "minutes", "plan", "guide"]
        for i in range(1, count + 1):
            did = f"doc_{i:03d}"
            pid = self.rng.choice(proj_ids)
            proj = self._entity_map[pid]
            dtype = self.rng.choice(doc_types)
            author = self.rng.choice(self._users)

            content_templates = [
                f"Tài liệu {dtype} cho {proj.name}. Phiên bản cập nhật bao gồm các thay đổi mới nhất về kiến trúc hệ thống và yêu cầu từ khách hàng.",
                f"Báo cáo tiến độ {proj.name}: Dự án đang ở giai đoạn {proj.status}. Có {self.rng.randint(1,5)} issue cần xử lý. Team đang tập trung vào các task ưu tiên cao.",
                f"Đề xuất cải tiến {proj.name}: Dựa trên phân tích hiệu suất gần đây, cần nâng cấp infrastructure và tối ưu database queries.",
                f"Hướng dẫn sử dụng module mới của {proj.name} cho team development. Bao gồm setup, configuration và best practices.",
                f"Phân tích rủi ro {proj.name}: Đánh giá các rủi ro tiềm ẩn và đề xuất giải pháp phòng ngừa cho quý tiếp theo.",
            ]

            doc = DocumentEntity(
                id=did, name=f"{dtype.title()} - {proj.name} v{self.rng.randint(1,3)}.{self.rng.randint(0,9)}",
                doc_type=dtype, content=self.rng.choice(content_templates),
                version=f"{self.rng.randint(1,3)}.{self.rng.randint(0,9)}",
                created_at=BASE_DATE + timedelta(days=self.rng.randint(-30, 40)),
            )
            self._add_entity(doc)
            self._documents.append(doc)
            self._add_rel(pid, did, RelationshipType.HAS_DOCUMENT)
            self._add_rel(did, author.id, RelationshipType.SENT_BY)

            # Some documents reference issues or meetings
            if self.rng.random() < 0.3 and self._project_issues.get(pid):
                iss_id = self.rng.choice(self._project_issues[pid])
                self._add_rel(did, iss_id, RelationshipType.REFERENCES)
            if self.rng.random() < 0.2 and self._project_meetings.get(pid):
                meet_id = self.rng.choice(self._project_meetings[pid])
                self._add_rel(did, meet_id, RelationshipType.REFERENCES)

    def _generate_messages(self, count: int = 700):
        proj_ids = [p.id for p in self._projects]
        channels = ["slack", "email", "teams", "internal_chat"]

        for i in range(1, count + 1):
            mid = f"msg_{i:03d}"
            sender = self.rng.choice(self._users)
            pid = self.rng.choice(proj_ids)
            proj = self._entity_map[pid]
            ts = BASE_DATE + timedelta(
                days=self.rng.randint(-30, 50),
                hours=self.rng.randint(8, 18),
                minutes=self.rng.randint(0, 59),
            )

            # Build realistic message content that references other entities
            mentioned_users = self.rng.sample(self._users, min(self.rng.randint(0, 3), len(self._users)))
            mentioned_names = [u.name for u in mentioned_users if u.id != sender.id]

            issue_ref = None
            task_ref = None
            if self.rng.random() < 0.4 and self._project_issues.get(pid):
                issue_ref = self.rng.choice(self._project_issues[pid])
            if self.rng.random() < 0.3 and self._project_tasks.get(pid):
                task_ref = self.rng.choice(self._project_tasks[pid])

            cust = self._entity_map.get(self._project_customer.get(pid))

            content_parts = []
            templates = [
                f"Update về {proj.name}: ",
                f"Về {proj.name}, ",
                f"FYI cho team về {proj.name}: ",
                f"Cần trao đổi về {proj.name}: ",
                f"@team Cập nhật {proj.name}: ",
            ]
            content_parts.append(self.rng.choice(templates))

            body_templates = [
                f"Đã hoàn thành review code cho sprint này. Còn {self.rng.randint(2,8)} PR cần merge.",
                f"Khách hàng {cust.name if cust else 'ABC'} phản hồi tốt về demo lần trước.",
                f"Cần thêm {self.rng.randint(1,3)} ngày để hoàn thiện tính năng này.",
                f"Phát hiện bug trong module thanh toán, cần fix urgent.",
                f"Tiến độ đang chậm {self.rng.randint(1,5)} ngày so với kế hoạch.",
                f"Đã deploy thành công lên staging environment.",
                f"Cần họp với {cust.name if cust else 'khách hàng'} để confirm requirements.",
                f"Performance test cho thấy response time tăng {self.rng.randint(20,80)}%.",
                f"Đã fix xong issue và đang chờ QA verify.",
                f"Sprint review tuần này sẽ demo feature mới cho stakeholder.",
                f"Database migration đã chạy thành công, không có downtime.",
                f"Cần discussion về thay đổi API contract với {cust.name if cust else 'partner'}.",
            ]
            content_parts.append(self.rng.choice(body_templates))

            if mentioned_names:
                content_parts.append(f" CC: {', '.join(mentioned_names[:2])}")
            if issue_ref:
                issue_name = self._entity_map[issue_ref].name
                content_parts.append(f" (liên quan đến {issue_name})")

            msg = MessageEntity(
                id=mid, name=f"Message #{i}",
                content="".join(content_parts),
                channel=self.rng.choice(channels),
                timestamp=ts,
                created_at=ts,
            )
            self._add_entity(msg)
            self._messages.append(msg)
            self._add_rel(mid, sender.id, RelationshipType.SENT_BY)
            self._add_rel(mid, pid, RelationshipType.BELONGS_TO)
            self._message_project[mid] = pid

            for mu in mentioned_users:
                if mu.id != sender.id:
                    self._add_rel(mid, mu.id, RelationshipType.MENTIONS)
            if issue_ref:
                self._add_rel(mid, issue_ref, RelationshipType.DISCUSSES)
            if task_ref:
                self._add_rel(mid, task_ref, RelationshipType.RELATED_TO)

    # ------------------------------------------------------------------
    # Full generation
    # ------------------------------------------------------------------
    def generate(self) -> Dataset:
        """Generate the complete dataset."""
        self._generate_departments()
        self._generate_teams()
        self._generate_users()
        self._assign_users_to_teams()
        self._generate_customers()
        self._generate_projects()
        self._generate_issues(count=80)
        self._generate_tasks(count=150)
        self._generate_meetings(count=70)
        self._generate_decisions(count=40)
        self._generate_campaigns(count=25)
        self._generate_documents(count=70)
        self._generate_messages(count=700)

        questions = self._generate_questions()

        return Dataset(
            entities=self.entities,
            relationships=self.relationships,
            questions=questions,
            version="1.0.0",
            seed=self.seed,
            generated_at=datetime.now(),
        )

    # ------------------------------------------------------------------
    # Question generation with ground truth
    # ------------------------------------------------------------------
    def _generate_questions(self) -> list[BenchmarkQuestion]:
        """Generate 100+ benchmark questions with ground truth from the dataset."""
        questions: list[BenchmarkQuestion] = []
        qid = 0

        # ===== A. SINGLE-HOP (15 questions) =====
        for p in self.rng.sample(self._projects, min(5, len(self._projects))):
            qid += 1
            # Find the team
            team_id = None
            for r in self.relationships:
                if r.target_id == p.id and r.type == RelationshipType.RESPONSIBLE_FOR:
                    team_id = r.source_id
                    break
            team_name = self._entity_map[team_id].name if team_id else "Unknown"
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"{p.name} thuộc team nào?",
                difficulty=QuestionDifficulty.SINGLE_HOP,
                category="single_hop",
                required_entities=[p.id, team_id] if team_id else [p.id],
                required_relationships=["Team -> responsible_for -> Project"],
                ground_truth_answer=f"{p.name} thuộc team {team_name}.",
                ground_truth_sources=[p.id, team_id] if team_id else [p.id],
                hop_count=1,
            ))

        for u in self.rng.sample(self._users, min(5, len(self._users))):
            qid += 1
            team_id = self._user_team.get(u.id)
            team_name = self._entity_map[team_id].name if team_id else "Unknown"
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"{u.name} thuộc team nào?",
                difficulty=QuestionDifficulty.SINGLE_HOP,
                category="single_hop",
                required_entities=[u.id, team_id] if team_id else [u.id],
                required_relationships=["User -> member_of -> Team"],
                ground_truth_answer=f"{u.name} thuộc team {team_name}.",
                ground_truth_sources=[u.id, team_id] if team_id else [u.id],
                hop_count=1,
            ))

        for p in self.rng.sample(self._projects, min(5, len(self._projects))):
            qid += 1
            cust_id = self._project_customer.get(p.id)
            cust_name = self._entity_map[cust_id].name if cust_id else "Unknown"
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"{p.name} phục vụ khách hàng nào?",
                difficulty=QuestionDifficulty.SINGLE_HOP,
                category="single_hop",
                required_entities=[p.id, cust_id] if cust_id else [p.id],
                required_relationships=["Team -> works_with -> Customer"],
                ground_truth_answer=f"{p.name} phục vụ khách hàng {cust_name}.",
                ground_truth_sources=[p.id, cust_id] if cust_id else [p.id],
                hop_count=1,
            ))

        # ===== B. TWO-HOP (15 questions) =====
        for p in self.rng.sample(self._projects, min(5, len(self._projects))):
            qid += 1
            team_id = None
            for r in self.relationships:
                if r.target_id == p.id and r.type == RelationshipType.RESPONSIBLE_FOR:
                    team_id = r.source_id
                    break
            dept_id = self._team_dept.get(team_id, "") if team_id else ""
            dept_name = self._entity_map[dept_id].name if dept_id else "Unknown"
            team_name = self._entity_map[team_id].name if team_id else "Unknown"
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"{p.name} thuộc phòng ban nào?",
                difficulty=QuestionDifficulty.TWO_HOP,
                category="two_hop",
                required_entities=[p.id, team_id, dept_id],
                required_relationships=["Team -> responsible_for -> Project", "Team -> belongs_to -> Department"],
                ground_truth_answer=f"{p.name} do team {team_name} phụ trách, thuộc phòng {dept_name}.",
                ground_truth_sources=[p.id, team_id, dept_id],
                hop_count=2,
            ))

        for u in self.rng.sample(self._users, min(5, len(self._users))):
            qid += 1
            team_id = self._user_team.get(u.id, "")
            projs = self._team_projects.get(team_id, [])
            proj_names = [self._entity_map[pid].name for pid in projs]
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"{u.name} đang tham gia những project nào?",
                difficulty=QuestionDifficulty.TWO_HOP,
                category="two_hop",
                required_entities=[u.id, team_id] + projs,
                required_relationships=["User -> member_of -> Team", "Team -> responsible_for -> Project"],
                ground_truth_answer=f"{u.name} thuộc team {self._entity_map[team_id].name if team_id else 'Unknown'}, phụ trách các project: {', '.join(proj_names) if proj_names else 'không có'}.",
                ground_truth_sources=[u.id, team_id] + projs,
                hop_count=2,
            ))

        for t in self.rng.sample(self._teams, min(5, len(self._teams))):
            qid += 1
            members = [u for u in self._users if self._user_team.get(u.id) == t.id]
            member_names = [m.name for m in members]
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Ai là thành viên của team {t.name}?",
                difficulty=QuestionDifficulty.TWO_HOP,
                category="two_hop",
                required_entities=[t.id] + [m.id for m in members],
                required_relationships=["User -> member_of -> Team"],
                ground_truth_answer=f"Team {t.name} có {len(members)} thành viên: {', '.join(member_names)}.",
                ground_truth_sources=[t.id] + [m.id for m in members],
                hop_count=1,
            ))

        # ===== C. MULTI-HOP (15 questions) =====
        # Find projects with issues discussed in meetings that led to decisions
        for p in self.rng.sample(self._projects, min(5, len(self._projects))):
            qid += 1
            issues = self._project_issues.get(p.id, [])
            meetings = self._project_meetings.get(p.id, [])
            decisions = []
            for mid in meetings:
                decisions.extend(self._meeting_decisions.get(mid, []))

            team_id = None
            for r in self.relationships:
                if r.target_id == p.id and r.type == RelationshipType.RESPONSIBLE_FOR:
                    team_id = r.source_id
                    break

            team_members = [u for u in self._users if self._user_team.get(u.id) == team_id]
            member_names = [m.name for m in team_members[:5]]

            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Ai trong team phụ trách {p.name} đã trao đổi về các vấn đề của dự án này?",
                difficulty=QuestionDifficulty.MULTI_HOP,
                category="multi_hop",
                required_entities=[p.id, team_id] + [u.id for u in team_members] + issues[:3],
                required_relationships=[
                    "Team -> responsible_for -> Project",
                    "User -> member_of -> Team",
                    "Project -> has_issue -> Issue",
                ],
                ground_truth_answer=f"Team {self._entity_map[team_id].name if team_id else 'Unknown'} phụ trách {p.name}. Các thành viên: {', '.join(member_names)}. Dự án có {len(issues)} issue.",
                ground_truth_sources=[p.id, team_id] + [u.id for u in team_members[:3]] + issues[:3],
                hop_count=3,
            ))

        # Decision chain: Meeting -> Decision -> affects Project -> Campaign
        for did in self.rng.sample(
            [d.id for d in self._decisions], min(5, len(self._decisions))
        ):
            qid += 1
            dec = self._entity_map[did]
            # Find meeting
            meeting_id = None
            for r in self.relationships:
                if r.target_id == did and r.type == RelationshipType.RESULTS_IN:
                    meeting_id = r.source_id
                    break
            # Find affected project
            proj_id = None
            for r in self.relationships:
                if r.source_id == did and r.type == RelationshipType.AFFECTS:
                    proj_id = r.target_id
                    break
            # Find campaigns changed
            campaigns = self._decision_campaigns.get(did, [])
            camp_names = [self._entity_map[c].name for c in campaigns]

            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Quyết định '{dec.description[:60]}...' ảnh hưởng đến những campaign nào?",
                difficulty=QuestionDifficulty.MULTI_HOP,
                category="multi_hop",
                required_entities=[did, meeting_id, proj_id] + campaigns,
                required_relationships=[
                    "Meeting -> results_in -> Decision",
                    "Decision -> affects -> Project",
                    "Decision -> changes -> Campaign",
                ],
                ground_truth_answer=f"Quyết định này ảnh hưởng đến {self._entity_map[proj_id].name if proj_id else 'Unknown'}. Các campaign bị thay đổi: {', '.join(camp_names) if camp_names else 'không có campaign nào bị ảnh hưởng trực tiếp'}.",
                ground_truth_sources=[did, meeting_id, proj_id] + campaigns,
                hop_count=3,
            ))

        # Issue -> Meeting -> Decision -> Campaign chain
        for iss in self.rng.sample(self._issues, min(5, len(self._issues))):
            qid += 1
            issue_meetings = self._issue_meetings.get(iss.id, [])
            related_decisions = []
            for mid in issue_meetings:
                related_decisions.extend(self._meeting_decisions.get(mid, []))
            related_campaigns = []
            for did in related_decisions:
                related_campaigns.extend(self._decision_campaigns.get(did, []))

            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"'{iss.description[:80]}' đã dẫn đến những quyết định và thay đổi campaign nào?",
                difficulty=QuestionDifficulty.MULTI_HOP,
                category="multi_hop",
                required_entities=[iss.id] + issue_meetings + related_decisions + related_campaigns,
                required_relationships=[
                    "Meeting -> discusses -> Issue",
                    "Meeting -> results_in -> Decision",
                    "Decision -> changes -> Campaign",
                ],
                ground_truth_answer=(
                    f"Issue này được thảo luận trong {len(issue_meetings)} cuộc họp, "
                    f"dẫn đến {len(related_decisions)} quyết định"
                    + (f" và ảnh hưởng đến {len(related_campaigns)} campaign." if related_campaigns else ".")
                ),
                ground_truth_sources=[iss.id] + issue_meetings + related_decisions + related_campaigns,
                hop_count=4,
            ))

        # ===== D. TEMPORAL (12 questions) =====
        cutoff_dates = [
            BASE_DATE + timedelta(days=d) for d in [0, 10, 20, 30]
        ]
        for cutoff in cutoff_dates:
            qid += 1
            after_issues = [
                iss for iss in self._issues
                if iss.reported_date and iss.reported_date > cutoff
            ]
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Những issue nào được báo cáo sau ngày {cutoff.strftime('%d/%m/%Y')}?",
                difficulty=QuestionDifficulty.TEMPORAL,
                category="temporal",
                required_entities=[iss.id for iss in after_issues[:10]],
                required_relationships=[],
                ground_truth_answer=f"Có {len(after_issues)} issue được báo cáo sau {cutoff.strftime('%d/%m/%Y')}: {', '.join([iss.name for iss in after_issues[:5]])}{'...' if len(after_issues) > 5 else ''}.",
                ground_truth_sources=[iss.id for iss in after_issues[:10]],
                hop_count=1,
            ))

        for cutoff in cutoff_dates[:2]:
            qid += 1
            after_meetings = [
                m for m in self._meetings
                if m.date and m.date > cutoff
            ]
            # Find decisions from those meetings
            after_decisions = []
            for m in after_meetings:
                after_decisions.extend(self._meeting_decisions.get(m.id, []))
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Những quyết định nào được đưa ra sau ngày {cutoff.strftime('%d/%m/%Y')}?",
                difficulty=QuestionDifficulty.TEMPORAL,
                category="temporal",
                required_entities=[d for d in after_decisions[:10]],
                required_relationships=["Meeting -> results_in -> Decision"],
                ground_truth_answer=f"Có {len(after_decisions)} quyết định sau {cutoff.strftime('%d/%m/%Y')}.",
                ground_truth_sources=after_decisions[:10],
                hop_count=2,
            ))

        # Temporal: messages in a time range about a project
        for p in self.rng.sample(self._projects, min(3, len(self._projects))):
            qid += 1
            start_range = BASE_DATE + timedelta(days=self.rng.randint(0, 20))
            end_range = start_range + timedelta(days=14)
            msgs_in_range = [
                m for m in self._messages
                if self._message_project.get(m.id) == p.id
                and m.timestamp and start_range <= m.timestamp <= end_range
            ]
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Có bao nhiêu tin nhắn về {p.name} trong khoảng {start_range.strftime('%d/%m')} đến {end_range.strftime('%d/%m/%Y')}?",
                difficulty=QuestionDifficulty.TEMPORAL,
                category="temporal",
                required_entities=[p.id] + [m.id for m in msgs_in_range[:5]],
                required_relationships=["Message -> belongs_to -> Project"],
                ground_truth_answer=f"Có {len(msgs_in_range)} tin nhắn về {p.name} trong khoảng thời gian này.",
                ground_truth_sources=[m.id for m in msgs_in_range[:10]],
                hop_count=1,
            ))

        # ===== E. CROSS-SOURCE (10 questions) =====
        for p in self.rng.sample(self._projects, min(5, len(self._projects))):
            qid += 1
            # Cross-reference: documents + meetings + messages about the same project
            docs = [r.target_id for r in self.relationships
                    if r.source_id == p.id and r.type == RelationshipType.HAS_DOCUMENT]
            meets = self._project_meetings.get(p.id, [])
            msgs = [m.id for m in self._messages if self._message_project.get(m.id) == p.id]

            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Tổng hợp tất cả thông tin từ documents, meetings và messages về {p.name}. Có bao nhiêu nguồn thông tin?",
                difficulty=QuestionDifficulty.CROSS_SOURCE,
                category="cross_source",
                required_entities=[p.id] + docs[:3] + meets[:3] + msgs[:3],
                required_relationships=[
                    "Project -> has_document -> Document",
                    "Project -> has_meeting -> Meeting",
                    "Message -> belongs_to -> Project",
                ],
                ground_truth_answer=f"{p.name} có {len(docs)} documents, {len(meets)} meetings, và {len(msgs)} messages.",
                ground_truth_sources=docs[:3] + meets[:3] + msgs[:3],
                hop_count=1,
            ))

        for m in self.rng.sample(self._meetings[:20], min(5, len(self._meetings[:20]))):
            qid += 1
            # Meeting -> what decisions -> what project effects -> what messages mention
            decs = self._meeting_decisions.get(m.id, [])
            affected_projs = []
            for d in decs:
                for r in self.relationships:
                    if r.source_id == d and r.type == RelationshipType.AFFECTS:
                        affected_projs.append(r.target_id)

            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Cuộc họp '{m.name}' đã đưa ra quyết định gì và ảnh hưởng đến project nào?",
                difficulty=QuestionDifficulty.CROSS_SOURCE,
                category="cross_source",
                required_entities=[m.id] + decs + affected_projs,
                required_relationships=[
                    "Meeting -> results_in -> Decision",
                    "Decision -> affects -> Project",
                ],
                ground_truth_answer=f"Cuộc họp đưa ra {len(decs)} quyết định, ảnh hưởng đến {len(affected_projs)} project.",
                ground_truth_sources=[m.id] + decs + affected_projs,
                hop_count=2,
            ))

        # ===== F. AGGREGATION (12 questions) =====
        for t in self.rng.sample(self._teams, min(4, len(self._teams))):
            qid += 1
            projs = self._team_projects.get(t.id, [])
            total_issues = sum(len(self._project_issues.get(pid, [])) for pid in projs)
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Team {t.name} đang có bao nhiêu issue trên tất cả project?",
                difficulty=QuestionDifficulty.AGGREGATION,
                category="aggregation",
                required_entities=[t.id] + projs,
                required_relationships=[
                    "Team -> responsible_for -> Project",
                    "Project -> has_issue -> Issue",
                ],
                ground_truth_answer=f"Team {t.name} có tổng cộng {total_issues} issue trên {len(projs)} project.",
                ground_truth_sources=[t.id] + projs,
                hop_count=2,
            ))

        for p in self.rng.sample(self._projects, min(4, len(self._projects))):
            qid += 1
            tasks = self._project_tasks.get(p.id, [])
            done_tasks = [tid for tid in tasks if self._entity_map[tid].status == "done"]
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Trong {p.name}, bao nhiêu task đã hoàn thành và bao nhiêu chưa?",
                difficulty=QuestionDifficulty.AGGREGATION,
                category="aggregation",
                required_entities=[p.id] + tasks[:10],
                required_relationships=["Project -> has_task -> Task"],
                ground_truth_answer=f"{p.name} có {len(done_tasks)}/{len(tasks)} task đã hoàn thành.",
                ground_truth_sources=[p.id] + tasks[:10],
                hop_count=1,
            ))

        # Count critical issues by severity
        for sev in ["critical", "high"]:
            qid += 1
            sev_issues = [iss for iss in self._issues if iss.severity == sev]
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Có bao nhiêu issue có mức độ nghiêm trọng '{sev}' đang open?",
                difficulty=QuestionDifficulty.AGGREGATION,
                category="aggregation",
                required_entities=[iss.id for iss in sev_issues if iss.status == "open"],
                required_relationships=[],
                ground_truth_answer=f"Có {len([i for i in sev_issues if i.status == 'open'])} issue {sev} đang open.",
                ground_truth_sources=[iss.id for iss in sev_issues if iss.status == "open"],
                hop_count=1,
            ))

        # Messages per project
        for p in self.rng.sample(self._projects, min(2, len(self._projects))):
            qid += 1
            msg_count = sum(1 for m in self._messages if self._message_project.get(m.id) == p.id)
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Tổng số tin nhắn trao đổi về {p.name} là bao nhiêu?",
                difficulty=QuestionDifficulty.AGGREGATION,
                category="aggregation",
                required_entities=[p.id],
                required_relationships=["Message -> belongs_to -> Project"],
                ground_truth_answer=f"Có {msg_count} tin nhắn về {p.name}.",
                ground_truth_sources=[p.id],
                hop_count=1,
            ))

        # ===== G. RELATIONSHIP REASONING (10 questions) =====
        for cust in self.rng.sample(self._customers, min(5, len(self._customers))):
            qid += 1
            # Find all projects for this customer
            cust_projs = [pid for pid, cid in self._project_customer.items() if cid == cust.id]
            proj_names = [self._entity_map[pid].name for pid in cust_projs]
            # Find teams
            team_ids = set()
            for pid in cust_projs:
                for r in self.relationships:
                    if r.target_id == pid and r.type == RelationshipType.RESPONSIBLE_FOR:
                        team_ids.add(r.source_id)
            team_names = [self._entity_map[tid].name for tid in team_ids]

            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Những team nào đang làm việc với khách hàng {cust.name} và trên những project nào?",
                difficulty=QuestionDifficulty.RELATIONSHIP,
                category="relationship",
                required_entities=[cust.id] + cust_projs + list(team_ids),
                required_relationships=[
                    "Team -> works_with -> Customer",
                    "Team -> responsible_for -> Project",
                ],
                ground_truth_answer=f"Khách hàng {cust.name} có {len(cust_projs)} project: {', '.join(proj_names)}. Team: {', '.join(team_names)}.",
                ground_truth_sources=[cust.id] + cust_projs + list(team_ids),
                hop_count=2,
            ))

        for u in self.rng.sample(self._users, min(5, len(self._users))):
            qid += 1
            team_id = self._user_team.get(u.id, "")
            projs = self._team_projects.get(team_id, [])
            # Issues from user's projects
            user_issues = []
            for pid in projs:
                user_issues.extend(self._project_issues.get(pid, []))
            cust_ids = set(self._project_customer.get(pid) for pid in projs if self._project_customer.get(pid))
            cust_names = [self._entity_map[cid].name for cid in cust_ids]

            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"{u.name} đang liên quan đến những khách hàng nào thông qua project?",
                difficulty=QuestionDifficulty.RELATIONSHIP,
                category="relationship",
                required_entities=[u.id, team_id] + projs + list(cust_ids),
                required_relationships=[
                    "User -> member_of -> Team",
                    "Team -> responsible_for -> Project",
                    "Team -> works_with -> Customer",
                ],
                ground_truth_answer=f"{u.name} liên quan đến {len(cust_ids)} khách hàng: {', '.join(cust_names)} qua {len(projs)} project.",
                ground_truth_sources=[u.id, team_id] + list(cust_ids),
                hop_count=3,
            ))

        # ===== H. EXECUTIVE QUESTIONS (10 questions) =====
        for p in self.rng.sample(self._projects, min(5, len(self._projects))):
            qid += 1
            issues = self._project_issues.get(p.id, [])
            open_issues = [iid for iid in issues if self._entity_map[iid].status in ("open", "in_progress")]
            tasks = self._project_tasks.get(p.id, [])
            done_tasks = [tid for tid in tasks if self._entity_map[tid].status == "done"]
            recent_msgs = sorted(
                [m for m in self._messages if self._message_project.get(m.id) == p.id],
                key=lambda x: x.timestamp or BASE_DATE,
                reverse=True,
            )[:5]

            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Tình hình {p.name} hiện tại thế nào?",
                difficulty=QuestionDifficulty.EXECUTIVE,
                category="executive",
                required_entities=[p.id] + issues[:3] + tasks[:3],
                required_relationships=[
                    "Project -> has_issue -> Issue",
                    "Project -> has_task -> Task",
                ],
                ground_truth_answer=(
                    f"{p.name} (status: {p.status}, priority: {p.priority}). "
                    f"Có {len(issues)} issue ({len(open_issues)} đang mở), "
                    f"{len(done_tasks)}/{len(tasks)} task hoàn thành."
                ),
                ground_truth_sources=[p.id] + issues[:5] + tasks[:5] + [m.id for m in recent_msgs],
                hop_count=2,
            ))

        delayed_projs = [p for p in self._projects if p.status == "delayed"]
        for p in delayed_projs[:3]:
            qid += 1
            issues = self._project_issues.get(p.id, [])
            critical_issues = [iid for iid in issues if self._entity_map[iid].severity in ("critical", "high")]
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Tại sao {p.name} bị chậm tiến độ?",
                difficulty=QuestionDifficulty.EXECUTIVE,
                category="executive",
                required_entities=[p.id] + critical_issues[:5],
                required_relationships=[
                    "Project -> has_issue -> Issue",
                ],
                ground_truth_answer=f"{p.name} bị delay. Có {len(critical_issues)} issue critical/high: {', '.join([self._entity_map[iid].description[:50] for iid in critical_issues[:3]])}.",
                ground_truth_sources=[p.id] + critical_issues[:5],
                hop_count=2,
            ))

        # "Team nào đang gặp vấn đề với khách hàng X?"
        for cust in self.rng.sample(self._customers, min(2, len(self._customers))):
            qid += 1
            cust_projs = [pid for pid, cid in self._project_customer.items() if cid == cust.id]
            issues_for_cust = []
            for pid in cust_projs:
                issues_for_cust.extend(self._project_issues.get(pid, []))
            teams = set()
            for pid in cust_projs:
                for r in self.relationships:
                    if r.target_id == pid and r.type == RelationshipType.RESPONSIBLE_FOR:
                        teams.add(r.source_id)

            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"Team nào đang gặp vấn đề với khách hàng {cust.name}?",
                difficulty=QuestionDifficulty.EXECUTIVE,
                category="executive",
                required_entities=[cust.id] + cust_projs + list(teams) + issues_for_cust[:5],
                required_relationships=[
                    "Team -> works_with -> Customer",
                    "Team -> responsible_for -> Project",
                    "Project -> has_issue -> Issue",
                ],
                ground_truth_answer=f"Các team {', '.join([self._entity_map[t].name for t in teams])} đang có {len(issues_for_cust)} issue liên quan đến {cust.name}.",
                ground_truth_sources=[cust.id] + list(teams) + issues_for_cust[:5],
                hop_count=3,
            ))

        # ===== I. DISTRACTOR QUESTIONS (6 questions) =====
        # Questions designed to confuse keyword-matching systems
        alpha_projs = [p for p in self._projects if "Alpha" in p.name]
        if len(alpha_projs) >= 2:
            for ap in alpha_projs:
                qid += 1
                team_id = None
                for r in self.relationships:
                    if r.target_id == ap.id and r.type == RelationshipType.RESPONSIBLE_FOR:
                        team_id = r.source_id
                        break
                issues = self._project_issues.get(ap.id, [])
                questions.append(BenchmarkQuestion(
                    question_id=f"Q{qid:03d}",
                    question=f"Hãy cho biết chi tiết về {ap.name} (không phải các project Alpha khác).",
                    difficulty=QuestionDifficulty.DISTRACTOR,
                    category="distractor",
                    required_entities=[ap.id, team_id] if team_id else [ap.id],
                    required_relationships=["Team -> responsible_for -> Project"],
                    ground_truth_answer=f"{ap.name}: status={ap.status}, priority={ap.priority}. Team: {self._entity_map[team_id].name if team_id else 'Unknown'}. Issues: {len(issues)}.",
                    ground_truth_sources=[ap.id],
                    hop_count=1,
                    distractor_entities=[p.id for p in alpha_projs if p.id != ap.id],
                ))

        # Campaign Q4 distractor
        q4_campaigns = [c for c in self._campaigns if "Q4" in c.name]
        if len(q4_campaigns) >= 2:
            for camp in q4_campaigns[:2]:
                qid += 1
                # Find the project
                proj_id = None
                for r in self.relationships:
                    if r.source_id == camp.id and r.type == RelationshipType.TARGETS:
                        proj_id = r.target_id
                        break

                questions.append(BenchmarkQuestion(
                    question_id=f"Q{qid:03d}",
                    question=f"Chi tiết về '{camp.name}' — campaign này target project nào?",
                    difficulty=QuestionDifficulty.DISTRACTOR,
                    category="distractor",
                    required_entities=[camp.id, proj_id] if proj_id else [camp.id],
                    required_relationships=["Campaign -> targets -> Project"],
                    ground_truth_answer=f"Campaign '{camp.name}' (type: {camp.campaign_type}, status: {camp.status}) target {self._entity_map[proj_id].name if proj_id else 'Unknown'}.",
                    ground_truth_sources=[camp.id, proj_id] if proj_id else [camp.id],
                    hop_count=1,
                    distractor_entities=[c.id for c in q4_campaigns if c.id != camp.id],
                ))

        # Similar user names
        users_sorted = sorted(self._users, key=lambda u: u.name)
        for idx in range(min(2, len(users_sorted) - 1)):
            u = users_sorted[idx]
            qid += 1
            team_id = self._user_team.get(u.id, "")
            projs = self._team_projects.get(team_id, [])
            questions.append(BenchmarkQuestion(
                question_id=f"Q{qid:03d}",
                question=f"{u.name} chịu trách nhiệm gì trong công ty?",
                difficulty=QuestionDifficulty.DISTRACTOR,
                category="distractor",
                required_entities=[u.id, team_id],
                required_relationships=["User -> member_of -> Team", "Team -> responsible_for -> Project"],
                ground_truth_answer=f"{u.name} (role: {u.role}) thuộc team {self._entity_map[team_id].name if team_id else 'Unknown'}, phụ trách {len(projs)} project.",
                ground_truth_sources=[u.id, team_id] + projs,
                hop_count=2,
            ))

        # Pad to at least 100 questions with extra varieties
        while len(questions) < 100:
            qid += 1
            q_type = self.rng.choice(["hop2_extra", "agg_extra", "exec_extra", "rel_extra"])

            if q_type == "hop2_extra":
                p = self.rng.choice(self._projects)
                team_id = None
                for r in self.relationships:
                    if r.target_id == p.id and r.type == RelationshipType.RESPONSIBLE_FOR:
                        team_id = r.source_id
                        break
                members = [u for u in self._users if self._user_team.get(u.id) == team_id]
                questions.append(BenchmarkQuestion(
                    question_id=f"Q{qid:03d}",
                    question=f"Liệt kê tất cả thành viên team phụ trách {p.name}.",
                    difficulty=QuestionDifficulty.TWO_HOP,
                    category="two_hop",
                    required_entities=[p.id, team_id] + [m.id for m in members],
                    required_relationships=["Team -> responsible_for -> Project", "User -> member_of -> Team"],
                    ground_truth_answer=f"Team {self._entity_map[team_id].name if team_id else 'Unknown'} phụ trách {p.name}: {', '.join([m.name for m in members])} ({len(members)} người).",
                    ground_truth_sources=[p.id, team_id] + [m.id for m in members],
                    hop_count=2,
                ))
            elif q_type == "agg_extra":
                dept = self.rng.choice(self._departments)
                dept_teams = [t for t in self._teams if self._team_dept.get(t.id) == dept.id]
                total_members = sum(1 for u in self._users if self._user_team.get(u.id) in [t.id for t in dept_teams])
                questions.append(BenchmarkQuestion(
                    question_id=f"Q{qid:03d}",
                    question=f"Phòng {dept.name} có bao nhiêu team và bao nhiêu nhân viên?",
                    difficulty=QuestionDifficulty.AGGREGATION,
                    category="aggregation",
                    required_entities=[dept.id] + [t.id for t in dept_teams],
                    required_relationships=["Team -> belongs_to -> Department", "User -> member_of -> Team"],
                    ground_truth_answer=f"Phòng {dept.name} có {len(dept_teams)} team với tổng cộng {total_members} nhân viên.",
                    ground_truth_sources=[dept.id] + [t.id for t in dept_teams],
                    hop_count=2,
                ))
            elif q_type == "exec_extra":
                cust = self.rng.choice(self._customers)
                cust_projs = [pid for pid, cid in self._project_customer.items() if cid == cust.id]
                statuses = [self._entity_map[pid].status for pid in cust_projs]
                questions.append(BenchmarkQuestion(
                    question_id=f"Q{qid:03d}",
                    question=f"Tình trạng tất cả các dự án cho khách hàng {cust.name} hiện tại thế nào?",
                    difficulty=QuestionDifficulty.EXECUTIVE,
                    category="executive",
                    required_entities=[cust.id] + cust_projs,
                    required_relationships=["Team -> works_with -> Customer", "Team -> responsible_for -> Project"],
                    ground_truth_answer=f"Khách hàng {cust.name} có {len(cust_projs)} dự án: {', '.join([f'{self._entity_map[pid].name} ({self._entity_map[pid].status})' for pid in cust_projs])}.",
                    ground_truth_sources=[cust.id] + cust_projs,
                    hop_count=2,
                ))
            else:
                t = self.rng.choice(self._teams)
                projs = self._team_projects.get(t.id, [])
                custs = set(self._project_customer.get(pid) for pid in projs if self._project_customer.get(pid))
                questions.append(BenchmarkQuestion(
                    question_id=f"Q{qid:03d}",
                    question=f"Team {t.name} đang phục vụ những khách hàng nào?",
                    difficulty=QuestionDifficulty.RELATIONSHIP,
                    category="relationship",
                    required_entities=[t.id] + projs + list(custs),
                    required_relationships=["Team -> responsible_for -> Project", "Team -> works_with -> Customer"],
                    ground_truth_answer=f"Team {t.name} phục vụ {len(custs)} khách hàng: {', '.join([self._entity_map[cid].name for cid in custs])}.",
                    ground_truth_sources=[t.id] + list(custs),
                    hop_count=2,
                ))

        return questions


def save_dataset(dataset: Dataset, output_dir: Path):
    """Save the dataset to JSON files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save entities
    entities_data = [e.model_dump(mode="json") for e in dataset.entities]
    with open(output_dir / "entities.json", "w", encoding="utf-8") as f:
        json.dump(entities_data, f, ensure_ascii=False, indent=2, default=str)

    # Save relationships
    rels_data = [r.model_dump(mode="json") for r in dataset.relationships]
    with open(output_dir / "relationships.json", "w", encoding="utf-8") as f:
        json.dump(rels_data, f, ensure_ascii=False, indent=2, default=str)

    # Save questions with ground truth
    questions_data = [q.model_dump(mode="json") for q in dataset.questions]
    with open(output_dir / "questions.json", "w", encoding="utf-8") as f:
        json.dump(questions_data, f, ensure_ascii=False, indent=2, default=str)

    # Save full dataset
    full_data = dataset.model_dump(mode="json")
    with open(output_dir / "dataset_full.json", "w", encoding="utf-8") as f:
        json.dump(full_data, f, ensure_ascii=False, indent=2, default=str)

    # Summary
    summary = {
        "version": dataset.version,
        "seed": dataset.seed,
        "generated_at": str(dataset.generated_at),
        "entity_counts": {},
        "relationship_count": len(dataset.relationships),
        "question_count": len(dataset.questions),
        "question_categories": {},
    }
    for e in dataset.entities:
        et = e.type.value if hasattr(e.type, 'value') else str(e.type)
        summary["entity_counts"][et] = summary["entity_counts"].get(et, 0) + 1
    for q in dataset.questions:
        cat = q.category
        summary["question_categories"][cat] = summary["question_categories"].get(cat, 0) + 1

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"Dataset saved to {output_dir}")
    print(f"  Entities:      {len(dataset.entities)}")
    print(f"  Relationships: {len(dataset.relationships)}")
    print(f"  Questions:     {len(dataset.questions)}")
    for cat, cnt in summary["question_categories"].items():
        print(f"    {cat}: {cnt}")
