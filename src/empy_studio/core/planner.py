from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .project_service import ProjectDetection
from .task_intake import ProductTask

PlanStatus = Literal[
    "draft",
    "approved",
    "cancelled",
]
RiskLevel = Literal[
    "low",
    "medium",
    "high",
]
AgentRole = Literal[
    "discovery",
    "frontend",
    "backend",
    "coordinator",
    "quality",
    "security",
    "release",
]

IMPLEMENTATION_TERMS: tuple[str, ...] = (
    "add",
    "adjust",
    "build",
    "change",
    "create",
    "delete",
    "design",
    "develop",
    "enhance",
    "fix",
    "generate",
    "implement",
    "make",
    "modify",
    "polish",
    "redesign",
    "refactor",
    "remove",
    "rewrite",
    "save",
    "ship",
    "style",
    "store",
    "persist",
    "insert",
    "upsert",
    "submit",
    "send",
    "upload",
    "render",
    "display",
    "show",
    "update",
    "write",
    "link",
    "button",
    "page",
    "improve",
    "improvement",
    "responsive",
    "mobile",
    "tablet",
    "accessibility",
    "accessible",
    "wcag",
    "seo",
    "metadata",
    "meta",
    "navigation",
    "menu",
    "header",
    "footer",
    "hero",
    "gallery",
    "form",
    "dashboard",
    "chart",
    "graph",
    "table",
    "login",
    "logout",
    "sign in",
    "sign up",
    "signup",
    "register",
    "registration",
    "authentication",
    "authorization",
    "session",
    "password",
    "checkout",
    "payment",
    "cart",
    "upload",
    "افزود",
    "افزایش",
    "توسعه",
    "بهبود",
    "بهتر",
    "زیباتر",
    "تغییر",
    "اصلاح",
    "حذف",
    "ساخت",
    "بساز",
    "طراحی",
    "بازطراحی",
    "ارتقا",
    "پیاده",
    "رفع",
    "به‌روزرسان",
    "بروزرسان",
    "روزرسانی",
    "نوشتن",
    "لینک",
    "لینک‌دهی",
    "ارتباط",
    "همگام",
    "هماهنگ",
    "دکمه",
    "ایجاد",
    "درست کن",
    "درستش کن",
    "اضافه",
    "اضافه کن",
    "واکنش‌گرا",
    "واکنش گرا",
    "موبایل",
    "تبلت",
    "دسترسی‌پذیری",
    "دسترسی پذیری",
    "دسترسی‌پذیر",
    "دسترسی پذیر",
    "سئو",
    "متادیتا",
    "متا تگ",
    "ناوبری",
    "منو",
    "سربرگ",
    "هدر",
    "پانوشت",
    "فوتر",
    "هیرو",
    "بنر",
    "گالری",
    "فرم",
    "داشبورد",
    "نمودار",
    "گراف",
    "جدول",
    "ورود",
    "خروج",
    "ثبت‌نام",
    "ثبت نام",
    "نام‌نویسی",
    "رمز عبور",
    "احراز هویت",
    "نشست کاربر",
    "توکن",
    "پرداخت",
    "درگاه",
    "سبد خرید",
    "آپلود",
    "جمع‌آوری",
    "جمع اوری",
    "نمایش",
    "نمایش بده",
    "واکنش‌گرا کن",
    "واکنش گرا کن",
)

# Domain nouns are kept in ``IMPLEMENTATION_TERMS`` for backwards-compatible
# plan metadata, but a noun alone is not an imperative.  Without this split,
# a read-only request such as ``audit accessibility`` looked like a write.
IMPLEMENTATION_ACTION_TERMS: tuple[str, ...] = (
    "add",
    "adjust",
    "build",
    "change",
    "create",
    "delete",
    "design",
    "develop",
    "enhance",
    "fix",
    "generate",
    "implement",
    "make",
    "modify",
    "polish",
    "redesign",
    "refactor",
    "remove",
    "rewrite",
    "save",
    "ship",
    "style",
    "store",
    "persist",
    "insert",
    "upsert",
    "submit",
    "send",
    "render",
    "display",
    "show",
    "upload",
    "update",
    "write",
    "link",
    "improve",
    "enable",
    "configure",
    "integrate",
    "migrate",
    "support",
    "export",
    "import",
    "add",
    "افزود",
    "افزایش",
    "توسعه",
    "بهبود",
    "بهتر",
    "زیباتر",
    "تغییر",
    "اصلاح",
    "حذف",
    "ساخت",
    "بساز",
    "طراحی",
    "بازطراحی",
    "ارتقا",
    "پیاده",
    "رفع",
    "به‌روزرسان",
    "بروزرسان",
    "روزرسانی",
    "نوشتن",
    "لینک‌دهی",
    "ارتباط",
    "همگام",
    "هماهنگ",
    "ایجاد",
    "درست کن",
    "درستش کن",
    "اضافه",
    "اضافه کن",
    "پشتیبانی",
    "فعال کن",
    "فعال‌سازی",
    "یکپارچه",
    "اتصال",
    "مهاجرت",
    "خروجی",
    "ورودی",
    "گزارش‌گیری",
    "گزارش گیری",
    "جمع‌آوری",
    "جمع اوری",
    "نمایش",
    "نمایش بده",
    "واکنش‌گرا کن",
    "واکنش گرا کن",
)

# These vocabularies are deliberately kept in the core planner rather than
# in the web UI.  Requests can arrive through the CLI, a restored task, or a
# provider handoff, so routing must have one deterministic implementation.
# Terms are phrases where a phrase is safer than a broad substring (for
# example ``accessibility`` must never be interpreted as security ``access``).
FRONTEND_INTENT_TERMS: tuple[str, ...] = (
    "ui",
    "ux",
    "frontend",
    "front end",
    "web design",
    "website",
    "web site",
    "site",
    "homepage",
    "home page",
    "landing",
    "landing page",
    "redesign",
    "design",
    "layout",
    "template",
    "view",
    "show",
    "display",
    "render",
    "list",
    "page",
    "html",
    "css",
    "stylesheet",
    "style",
    "theme",
    "font",
    "typography",
    "color",
    "colour",
    "asset",
    "assets",
    "image",
    "images",
    "icon",
    "logo",
    "navigation",
    "nav",
    "menu",
    "header",
    "footer",
    "hero",
    "banner",
    "gallery",
    "search",
    "search box",
    "search bar",
    "autocomplete",
    "filter",
    "filters",
    "sorting",
    "sort",
    "pagination",
    "infinite scroll",
    "comments",
    "comment",
    "reviews",
    "ratings",
    "rating",
    "notifications",
    "notification",
    "toast",
    "alert",
    "chat",
    "messaging",
    "conversation",
    "video",
    "video player",
    "dark mode",
    "light mode",
    "multilingual",
    "multi-language",
    "i18n",
    "translation",
    "cookie consent",
    "privacy policy",
    "terms of service",
    "social sharing",
    "download",
    "export",
    "import",
    "pwa",
    "offline",
    "push notifications",
    "rss",
    "feed",
    "form",
    "contact form",
    "input",
    "button",
    "link",
    "links",
    "broken link",
    "broken links",
    "card",
    "modal",
    "responsive",
    "mobile",
    "tablet",
    "desktop",
    "breakpoint",
    "interaction",
    "interactive",
    "javascript",
    "js interaction",
    "local storage",
    "localstorage",
    "browser storage",
    "accessibility",
    "accessible",
    "wcag",
    "a11y",
    "seo",
    "meta tags",
    "metadata",
    "meta data",
    "title tag",
    "canonical",
    "open graph",
    "structured data",
    "schema.org",
    "sitemap",
    "robots.txt",
    "favicon",
    "manifest.json",
    "dashboard",
    "chart",
    "graph",
    "plot",
    "sparkline",
    "table",
    "data table",
    "data grid",
    "datagrid",
    "grid",
    "login",
    "log in",
    "sign in",
    "signup",
    "sign up",
    "register",
    "registration",
    "password reset",
    "cart",
    "shopping cart",
    "checkout",
    "payment",
    "upload",
    "profile",
    "user profile",
    "admin panel",
    "پنل مدیریت",
    "drag and drop",
    "rtl",
    "right to left",
    "synchronize",
    "sync",
    "رابط کاربری",
    "رابط",
    "تجربه کاربری",
    "تجربهٔ کاربری",
    "سایت",
    "طراحی سایت",
    "صفحه",
    "صفحه اصلی",
    "صفحه اول",
    "صفحه خانه",
    "صفحه فرود",
    "لندینگ",
    "بازطراحی",
    "چیدمان",
    "قالب",
    "استایل",
    "تم",
    "نمایش",
    "نشان بده",
    "رندر",
    "لیست",
    "ظاهر",
    "فونت",
    "تایپوگرافی",
    "رنگ",
    "تصویر",
    "تصاویر",
    "آیکون",
    "لوگو",
    "ناوبری",
    "منوی ناوبری",
    "منو",
    "سربرگ",
    "هدر",
    "پانوشت",
    "فوتر",
    "هیرو",
    "بنر",
    "گالری",
    "جستجو",
    "جست‌وجو",
    "نوار جستجو",
    "تکمیل خودکار",
    "فیلتر",
    "فیلترها",
    "مرتب‌سازی",
    "مرتب سازی",
    "صفحه‌بندی",
    "صفحه بندی",
    "اسکرول بی‌نهایت",
    "نظرات",
    "نظر",
    "دیدگاه",
    "امتیاز",
    "اعلان",
    "اعلان‌ها",
    "پیام",
    "پیام‌رسانی",
    "چت",
    "گفتگو",
    "ویدئو",
    "پخش‌کننده ویدئو",
    "حالت تاریک",
    "حالت روشن",
    "چندزبانه",
    "ترجمه",
    "رضایت کوکی",
    "حریم خصوصی",
    "قوانین استفاده",
    "اشتراک‌گذاری",
    "دانلود",
    "خروجی",
    "ورودی",
    "آفلاین",
    "اعلان پوش",
    "خبرخوان",
    "فرم",
    "فرم تماس",
    "دکمه",
    "لینک",
    "لینک‌ها",
    "لینک‌های خراب",
    "کارت",
    "پنجره",
    "واکنش‌گرا",
    "واکنش گرا",
    "موبایل",
    "تبلت",
    "رومیزی",
    "دسترسی‌پذیری",
    "دسترسی پذیری",
    "دسترسی‌پذیر",
    "دسترسی پذیر",
    "استاندارد wcag",
    "سئو",
    "متادیتا",
    "متا تگ",
    "تگ عنوان",
    "کنونیکال",
    "داده ساختاریافته",
    "نقشه سایت",
    "نقشهٔ سایت",
    "داشبورد",
    "نمودار",
    "گراف",
    "رسم",
    "جدول",
    "جدول نمایش",
    "شبکه داده",
    "ورود",
    "وارد شدن",
    "ثبت‌نام",
    "ثبت نام",
    "نام‌نویسی",
    "سبد خرید",
    "پرداخت",
    "درگاه پرداخت",
    "آپلود",
    "بارگذاری فایل",
    "راست به چپ",
    "تعامل",
    "تعاملی",
    "جاوااسکریپت",
    "تعامل جاوااسکریپت",
    "ذخیره‌سازی محلی",
    "ذخیره سازی محلی",
    "ذخیره مرورگر",
    "فاوآیکون",
    "پروفایل کاربر",
    "همگام",
    "همگام‌سازی",
    "همگام سازی",
    "هماهنگ",
    "ارتباط",
    "ارتباط‌دهی",
    "ارتباط دهی",
)

BACKEND_INTENT_TERMS: tuple[str, ...] = (
    "backend",
    "back end",
    "server",
    "server-side",
    "api",
    "endpoint",
    "route",
    "routing",
    "controller",
    "service",
    "repository",
    "handler",
    "model",
    "database",
    "db",
    "schema",
    "migration",
    "migrations",
    "sql",
    "orm",
    "persist",
    "persistence",
    "insert",
    "upsert",
    "webhook",
    "queue",
    "cron",
    "email delivery",
    "send email",
    "mail",
    "search results",
    "full-text search",
    "comments api",
    "comment storage",
    "reviews api",
    "ratings api",
    "notifications api",
    "email notifications",
    "push notifications",
    "messaging",
    "websocket",
    "websockets",
    "chat server",
    "subscription",
    "subscriptions",
    "billing",
    "invoice",
    "invoicing",
    "analytics tracking",
    "analytics event",
    "captcha",
    "rate limiting",
    "rate limit",
    "cors",
    "audit log",
    "audit trail",
    "csv export",
    "csv import",
    "pdf generation",
    "report generation",
    "rss feed",
    "push service",
    "integration",
    "fetch from api",
    "load from server",
    "realtime",
    "real-time",
    "live data",
    "data source",
    "file storage",
    "object storage",
    "local storage api",
    "upload endpoint",
    "upload handler",
    "checkout",
    "payment",
    "cart total",
    "price calculation",
    "database table",
    "data model",
    "data schema",
    "ای پی آی",
    "ای‌پی‌آی",
    "سمت سرور",
    "سرور",
    "بک‌اند",
    "بک اند",
    "رابط برنامه‌نویسی",
    "رابط برنامه نویسی",
    "نقطه پایانی",
    "مسیر سمت سرور",
    "روت",
    "کنترلر",
    "سرویس",
    "ریپازیتوری",
    "هندلر",
    "مدل داده",
    "پایگاه داده",
    "دیتابیس",
    "طرح پایگاه داده",
    "اسکیما",
    "مهاجرت",
    "ذخیره",
    "ذخیره‌سازی",
    "ذخیره سازی",
    "ثبت اطلاعات",
    "رکورد",
    "وب‌هوک",
    "صف پردازش",
    "ایمیل",
    "ارسال ایمیل",
    "اتصال به api",
    "دریافت از api",
    "دریافت از سرور",
    "لحظه‌ای",
    "لحظه ای",
    "داده زنده",
    "منبع داده",
    "ذخیره فایل",
    "آپلود به سرور",
    "محاسبه مبلغ",
    "محاسبه قیمت",
    "جدول پایگاه داده",
    "جدول دیتابیس",
    "ذخیره‌سازی فایل",
    "ذخیره سازی فایل",
    "آپلود فایل",
    "آپلود تصویر",
    "ارسال فرم",
    "ارسال ایمیل",
    "جستجوی پایگاه داده",
    "نتایج جستجو",
    "رکوردهای جستجو",
    "ذخیره نظرات",
    "ثبت نظر",
    "اعلان ایمیلی",
    "اعلان پوش",
    "پیام‌رسانی سمت سرور",
    "وب‌سوکت",
    "چت بلادرنگ",
    "اشتراک",
    "صورتحساب",
    "فاکتور",
    "تحلیل رفتار",
    "ردیابی رویداد",
    "کپچا",
    "محدودیت درخواست",
    "محدودسازی درخواست",
    "لاگ ممیزی",
    "گزارش ممیزی",
    "خروجی csv",
    "ورودی csv",
    "تولید pdf",
    "تولید گزارش",
    "خبرخوان rss",
)

SECURITY_INTENT_TERMS: tuple[str, ...] = (
    "security",
    "secure",
    "vulnerability",
    "authentication",
    "authorization",
    "auth",
    "login",
    "log in",
    "logout",
    "log out",
    "sign in",
    "sign up",
    "signup",
    "register",
    "registration",
    "password",
    "password reset",
    "session",
    "token",
    "oauth",
    "oidc",
    "sso",
    "csrf",
    "xss",
    "csp",
    "encryption",
    "secret",
    "permission",
    "permissions",
    "role based access",
    "rbac",
    "pci",
    "card security",
    "input sanitization",
    "sanitize input",
    "security validation",
    "csrf protection",
    "xss protection",
    "captcha",
    "rate limiting",
    "rate limit",
    "cors",
    "audit log",
    "audit trail",
    "user roles",
    "role based permissions",
    "نقش کاربری",
    "نقش‌های کاربری",
    "سطح دسترسی",
    "کپچا",
    "محدودیت درخواست",
    "محدودسازی درخواست",
    "لاگ ممیزی",
    "گزارش ممیزی",
    "امنیت",
    "ایمن",
    "آسیب‌پذیری",
    "آسیب پذیری",
    "احراز هویت",
    "اعتبارسنجی هویت",
    "مجوز",
    "مجوزها",
    "سطح دسترسی",
    "ورود امن",
    "ورود کاربران",
    "ثبت‌نام کاربران",
    "ثبت نام کاربران",
    "رمز عبور",
    "بازیابی رمز",
    "نشست",
    "نشست کاربر",
    "توکن",
    "رمزنگاری",
    "محرمانه",
    "csrf",
    "xss",
    "پرداخت امن",
    "امنیت پرداخت",
    "کارت بانکی",
    "پاکسازی ورودی",
    "اعتبارسنجی امنیتی",
    "محافظت csrf",
    "محافظت xss",
)

ACCESSIBILITY_INTENT_TERMS: tuple[str, ...] = (
    "accessibility",
    "accessible",
    "wcag",
    "a11y",
    "aria",
    "screen reader",
    "keyboard navigation",
    "دسترسی‌پذیری",
    "دسترسی پذیری",
    "دسترسی‌پذیر",
    "دسترسی پذیر",
    "استاندارد wcag",
    "صفحه‌خوان",
    "صفحه خوان",
    "ناوبری با صفحه‌کلید",
    "ناوبری با صفحه کلید",
)

RELEASE_INTENT_TERMS: tuple[str, ...] = (
    "release",
    "deploy",
    "deployment",
    "publish",
    "production build",
    "directadmin",
    "direct admin",
    "استقرار",
    "انتشار",
    "نسخه نهایی",
    "نسخهٔ نهایی",
    "تحویل",
)

_FILE_INTENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".php",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".js",
        ".mjs",
        ".cjs",
        ".jsx",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".astro",
        ".py",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".sql",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".md",
        ".mdx",
        ".txt",
        ".xml",
    }
)

_FRONTEND_FILE_STEMS: frozenset[str] = frozenset(
    {
        "app",
        "index",
        "home",
        "homepage",
        "landing",
        "layout",
        "page",
        "header",
        "footer",
        "navbar",
        "navigation",
        "menu",
        "hero",
        "gallery",
        "dashboard",
        "chart",
        "graph",
        "form",
        "login",
        "signup",
        "register",
    }
)

_BACKEND_FILE_HINTS: tuple[str, ...] = (
    "service",
    "controller",
    "repository",
    "handler",
    "middleware",
    "model",
    "route",
    "api",
    "server",
    "database",
    "migration",
    "schema",
    "auth",
    "payment",
)


@dataclass(frozen=True)
class IntentProfile:
    """Deterministic domain signals extracted from a bilingual task.

    The profile is intentionally a small, serializable decision record.  It
    lets planner and context selection use the same interpretation without
    asking a provider to rediscover whether a ticket is UI, server, or
    security work.  ``domains`` contains only implementation-capable roles;
    discovery and quality are added by the plan policy.
    """

    implementation: bool
    domains: tuple[AgentRole, ...]
    frontend: bool
    backend: bool
    security: bool
    release: bool
    homepage: bool
    accessibility: bool
    frontend_assets: bool
    data_model: bool
    explicit_files: tuple[str, ...]

    def validate(self) -> None:
        known = {"frontend", "backend", "security", "release"}
        if any(domain not in known for domain in self.domains):
            raise ValueError("intent profile contains an unsupported domain")
        if tuple(dict.fromkeys(self.domains)) != self.domains:
            raise ValueError("intent profile domains must be unique")
        if self.frontend != ("frontend" in self.domains):
            raise ValueError("frontend intent flag is inconsistent")
        if self.backend != ("backend" in self.domains):
            raise ValueError("backend intent flag is inconsistent")
        if self.security != ("security" in self.domains):
            raise ValueError("security intent flag is inconsistent")
        if self.release != ("release" in self.domains):
            raise ValueError("release intent flag is inconsistent")

@dataclass(frozen=True)
class PlanStep:
    step_id: str
    title: str
    objective: str
    depends_on: tuple[str, ...]
    suggested_agent: AgentRole
    estimated_files: int
    risk: RiskLevel

    def validate(self) -> None:
        if not self.step_id.strip():
            raise ValueError("step_id cannot be empty")
        if not self.title.strip():
            raise ValueError("step title cannot be empty")
        if not self.objective.strip():
            raise ValueError("step objective cannot be empty")
        if self.estimated_files < 0:
            raise ValueError(
                "estimated_files cannot be negative"
            )
        if self.risk not in {
            "low",
            "medium",
            "high",
        }:
            raise ValueError(
                f"unsupported risk: {self.risk}"
            )


@dataclass(frozen=True)
class ExecutionPlan:
    schema_version: int
    plan_id: str
    task_id: str
    project_root: str
    project_type: str
    status: PlanStatus
    created_at: str
    approved_at: str | None
    summary: str
    risk: RiskLevel
    estimated_files: int
    estimated_agents: int
    estimated_tokens: int
    likely_paths: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    task_fingerprint: str

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "unsupported execution-plan schema"
            )
        if not self.plan_id.strip():
            raise ValueError("plan_id cannot be empty")
        if not self.task_id.strip():
            raise ValueError("task_id cannot be empty")
        if not self.summary.strip():
            raise ValueError("summary cannot be empty")
        if self.status not in {
            "draft",
            "approved",
            "cancelled",
        }:
            raise ValueError(
                f"unsupported plan status: {self.status}"
            )
        if self.estimated_files < 0:
            raise ValueError(
                "estimated_files cannot be negative"
            )
        if self.estimated_agents < 1:
            raise ValueError(
                "estimated_agents must be positive"
            )
        if self.estimated_tokens < 1:
            raise ValueError(
                "estimated_tokens must be positive"
            )
        if not self.steps:
            raise ValueError(
                "execution plan must contain steps"
            )

        known = {
            step.step_id
            for step in self.steps
        }
        if len(known) != len(self.steps):
            raise ValueError(
                "plan step IDs must be unique"
            )

        for step in self.steps:
            step.validate()
            unknown = set(step.depends_on) - known
            if unknown:
                raise ValueError(
                    "step contains unknown dependency"
                )

        if (
            self.status == "approved"
            and self.approved_at is None
        ):
            raise ValueError(
                "approved plan requires approved_at"
            )

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["steps"] = [
            asdict(step)
            for step in self.steps
        ]
        return value


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _fingerprint_task(
    task: ProductTask,
) -> str:
    payload = json.dumps(
        asdict(task),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _likely_paths(
    task: ProductTask,
    project: ProjectDetection,
) -> tuple[str, ...]:
    text = " ".join(
        (
            task.title,
            task.objective,
            *task.requirements,
        )
    )
    intent = classify_intent(text)
    project_type = (
        project.descriptor.project_type
    )

    paths: list[str] = []

    if project_type == "laravel":
        if intent.frontend:
            paths.extend(
                (
                    "resources/views/",
                    "resources/css/",
                    "resources/js/",
                    "public/",
                )
            )
        if intent.backend:
            paths.extend(
                (
                    "routes/",
                    "app/Http/",
                    "app/Models/",
                    "database/",
                )
            )
        paths.append("tests/")

    elif project_type == "python" or project_type == "node" or project_type == "rust":
        paths.extend(("src/", "tests/"))
    elif project_type == "php":
        # Plain PHP projects frequently keep the whole application directly
        # in a nested deployment root such as public_html/.  Assuming a
        # framework-style src/app/routes layout hid the real files and made a
        # low-relevance file the writer's only target.  Always include the
        # detected application root, then add only conventional directories
        # that actually exist beneath it.
        paths.append("./")
        verification_root = project.effective_verification_root
        for directory in ("src", "app", "public", "routes", "tests", "assets"):
            if (verification_root / directory).is_dir():
                paths.append(f"{directory}/")
        if intent.frontend:
            # Kept as an explicit branch for readability: the application
            # root was already added above and is deduplicated below.
            paths.append("./")
    elif project_type == "go":
        paths.extend(("./",))
    else:
        paths.extend(("./",))

    verification_root = project.effective_verification_root
    try:
        relative_root = verification_root.relative_to(project.descriptor.root).as_posix()
    except ValueError:
        relative_root = ""
    if relative_root and relative_root != ".":
        paths = [f"{relative_root}/{path.lstrip('./')}" for path in paths]
    return tuple(dict.fromkeys(paths))


def _risk(
    task: ProductTask,
    likely_paths: tuple[str, ...],
) -> RiskLevel:
    text = " ".join(
        (
            task.title,
            task.objective,
            *task.requirements,
        )
    )

    high_terms = (
        "database migration",
        "authentication",
        "authorization",
        "login",
        "sign in",
        "sign up",
        "password",
        "session",
        "oauth",
        "payment",
        "checkout",
        "security",
        "vulnerability",
        "delete",
        "production",
        "deployment",
        "احراز هویت",
        "ورود",
        "ثبت نام",
        "ثبت‌نام",
        "رمز عبور",
        "پرداخت",
        "درگاه",
        "امنیت",
        "آسیب پذیری",
        "آسیب‌پذیری",
    )
    medium_terms = (
        "backend",
        "api",
        "route",
        "controller",
        "integration",
        "refactor",
        "upload",
        "storage",
        "webhook",
        "realtime",
        "real-time",
        "database",
        "schema",
        "migration",
        "بک‌اند",
        "ای پی آی",
        "آپلود",
        "ذخیره",
        "لحظه‌ای",
        "لحظه ای",
    )

    if _contains_any_term(text, high_terms):
        return "high"
    if (
        _contains_any_term(text, medium_terms)
        or len(likely_paths) > 5
        or len(task.requirements) > 8
    ):
        return "medium"
    return "low"


def _normalise_intent_text(text: str) -> str:
    """Normalise common bilingual spelling variants before intent matching."""

    value = (
        text.casefold()
        .replace("\u200c", " ")
        .replace("\u200d", " ")
        .replace("\ufeff", " ")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("لینگ", "لینک")
    )
    # Arabic diacritics otherwise make an otherwise exact Persian phrase miss
    # its classification.  Keep punctuation because the word-boundary
    # matcher below deliberately treats it as a separator.
    value = re.sub(r"[\u064b-\u065f\u0670]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    """Match whole words/phrases without treating path fragments as domains."""

    normalized = _normalise_intent_text(text)
    return any(
        re.search(
            rf"(?<!\w){re.escape(_normalise_intent_text(term))}(?!\w)",
            normalized,
        )
        is not None
        for term in terms
    )


def _file_tokens(text: str) -> tuple[str, ...]:
    """Extract safe, project-relative-looking file tokens from task text.

    A ticket often names ``FinanceService.php`` or ``App.tsx`` without a
    directory.  The old path-only expression silently discarded those names,
    so the context selector could pass an unrelated file to the writer.  The
    extension allow-list prevents decimal versions and ordinary prose from
    becoming edit scope.
    """

    values: list[str] = []
    pattern = re.compile(
        r"(?<![\w./:-])(?:\.?[\w.-]+[/\\])*[\w.-]+\.[A-Za-z0-9_-]+",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        value = match.group(0).rstrip(".,;:!?)]}").replace("\\", "/")
        while value.startswith("./"):
            value = value[2:]
        suffix = Path(value).suffix.casefold()
        if suffix in _FILE_INTENT_EXTENSIONS:
            values.append(value)
    return tuple(dict.fromkeys(values))


def _file_role_signals(text: str) -> tuple[bool, bool]:
    """Infer a narrow role from explicitly named source files.

    File names supplement natural language; they never override an explicit
    domain such as ``database`` or ``security``.  The basename check is
    intentionally limited to common UI and server conventions so a generic
    ``worker.py`` does not become frontend work merely because it is a file.
    """

    frontend = False
    backend = False
    for value in _file_tokens(text):
        path = Path(value)
        name = path.name.casefold()
        suffix = path.suffix.casefold()
        stem = path.stem.casefold()
        path_parts = {part.casefold() for part in path.parts[:-1]}
        if name.endswith(".blade.php"):
            frontend = True
        if suffix in {
            ".css",
            ".scss",
            ".sass",
            ".less",
            ".html",
            ".htm",
            ".svg",
            ".tsx",
            ".jsx",
            ".vue",
            ".svelte",
            ".astro",
        }:
            frontend = True
        if suffix in {".js", ".mjs", ".cjs", ".ts"} and path_parts & {
            "asset",
            "assets",
            "component",
            "components",
            "css",
            "frontend",
            "page",
            "pages",
            "public",
            "script",
            "scripts",
            "style",
            "styles",
            "template",
            "templates",
            "view",
            "views",
        }:
            frontend = True
        if stem in _FRONTEND_FILE_STEMS or stem.removesuffix(".blade") in _FRONTEND_FILE_STEMS:
            frontend = True
        if any(hint in stem for hint in _BACKEND_FILE_HINTS):
            backend = True
        if suffix in {".sql"} or name in {"composer.json", "package.json", "pyproject.toml"}:
            backend = True
        if any(part.casefold() in {"api", "server", "backend", "controllers", "services", "models", "database", "migrations"}
               for part in path.parts[:-1]):
            backend = True
        # A plain PHP index is the presentation entry point in a typical
        # imported DirectAdmin site.  Server terms elsewhere in the ticket
        # can still add backend alongside it.
        if suffix == ".php" and stem in {"index", "home", "homepage", "login", "signup", "register"}:
            frontend = True
    return frontend, backend


def _requests_data_model_changes(text: str) -> bool:
    """Return true only for an explicit persistence/schema change.

    ``table`` and ``record`` are common presentation words.  Treating either
    as a database request gave a UI-only table ownership of SQL migrations.
    Schema terms or a persistence verb plus a data subject are required.
    """

    normalized = _normalise_intent_text(text)
    schema_terms = (
        "database",
        "db",
        "schema",
        "migration",
        "migrations",
        "sql",
        "orm",
        "data model",
        "data schema",
        "database table",
        "table schema",
        "پایگاه داده",
        "دیتابیس",
        "اسکیما",
        "طرح پایگاه داده",
        "جدول پایگاه داده",
        "جدول دیتابیس",
        "مدل داده",
    )
    if _contains_any_term(normalized, schema_terms):
        return True

    table_operation = (
        "create table",
        "alter table",
        "drop table",
        "delete table",
        "add table schema",
        "ایجاد جدول پایگاه",
        "ساخت جدول پایگاه",
        "تغییر جدول پایگاه",
        "حذف جدول پایگاه",
    )
    if _contains_any_term(normalized, table_operation) or re.search(
        r"(?<!\w)(?:create|alter|drop|delete|remove|migrate)\s+(?:an?\s+)?[\w-]+\s+table(?!\w)",
        normalized,
    ) or re.search(
        r"(?:ایجاد|ساخت|تغییر|حذف|مهاجرت)\s+[^\s]+\s+جدول(?!\w)",
        normalized,
    ):
        return True

    persistence_actions = (
        "persist",
        "persistence",
        "save",
        "store",
        "insert",
        "upsert",
        "persisted",
        "ذخیره",
        "ذخیره سازی",
        "ذخیره‌سازی",
        "ثبت اطلاعات",
        "ثبت رکورد",
        "ثبت سوابق",
    )
    data_subjects = (
        "data",
        "record",
        "records",
        "history",
        "historical",
        "entity",
        "entities",
        "information",
        "سوابق",
        "تاریخچه",
        "رکورد",
        "اطلاعات",
        "موجودیت",
    )
    persisted = _contains_any_term(normalized, persistence_actions) and _contains_any_term(
        normalized,
        data_subjects,
    )
    # ``record`` is both a persistence verb and the noun used by a data-grid
    # ticket.  Only treat it as a write when presentation language does not
    # clearly say that records are being displayed.
    record_action = _contains_any_term(normalized, ("record", "ثبت")) and not _contains_any_term(
        normalized,
        (
            "show",
            "display",
            "render",
            "list",
            "table",
            "grid",
            "view",
            "نمایش",
            "لیست",
            "جدول",
            "شبکه",
        ),
    )
    return persisted or (record_action and _contains_any_term(normalized, data_subjects))


def requests_data_model_changes(text: str) -> bool:
    """Public stable wrapper used by context selection and integrations."""

    return _requests_data_model_changes(text)


_LOCAL_STORAGE_TERMS: tuple[str, ...] = (
    "local storage",
    "localstorage",
    "browser storage",
    "ذخیره‌سازی محلی",
    "ذخیره سازی محلی",
    "ذخیره مرورگر",
)
_SERVER_DATA_BOUNDARY_TERMS: tuple[str, ...] = (
    "api",
    "endpoint",
    "server",
    "backend",
    "route",
    "controller",
    "service",
    "database",
    "db",
    "schema",
    "migration",
    "webhook",
    "upload endpoint",
    "دریافت از api",
    "دریافت از سرور",
    "سمت سرور",
    "پایگاه داده",
)


def _is_local_storage_only(text: str) -> bool:
    return _contains_any_term(text, _LOCAL_STORAGE_TERMS) and not _contains_any_term(
        text,
        _SERVER_DATA_BOUNDARY_TERMS,
    )


def _has_dynamic_data_signal(text: str) -> bool:
    """Detect data plumbing that makes a visual request multi-domain."""

    if _is_local_storage_only(text):
        return False

    return _contains_any_term(
        text,
        (
            "api",
            "endpoint",
            "server",
            "backend",
            "route",
            "controller",
            "service",
            "database",
            "db",
            "schema",
            "migration",
            "persist",
            "save",
            "store",
            "insert",
            "storage",
            "file storage",
            "webhook",
            "fetch",
            "load from server",
            "data source",
            "live",
            "realtime",
            "real-time",
            "real time",
            "دریافت از api",
            "دریافت از سرور",
            "سمت سرور",
            "پایگاه داده",
            "ذخیره",
            "ثبت اطلاعات",
            "ذخیره‌سازی",
            "ذخیره سازی",
            "لحظه‌ای",
            "لحظه ای",
            "داده زنده",
            "منبع داده",
        ),
    )


def classify_intent(text: str) -> IntentProfile:
    """Classify all implementation domains in one bilingual pass.

    The classifier is intentionally rule based and deterministic.  It is a
    routing contract, not an attempt to infer product intent from a provider:
    a visual request can receive frontend plus backend/security when its
    behavior crosses those boundaries, while a purely visual table or
    accessibility request remains frontend-only.
    """

    normalized = _normalise_intent_text(text)
    implementation = _contains_any_term(normalized, IMPLEMENTATION_ACTION_TERMS)
    homepage = _contains_any_term(
        normalized,
        (
            "homepage",
            "home page",
            "landing page",
            "landing",
            "index page",
            "home screen",
            "ایندکس",
            "صفحه اول",
            "صفحه اصلی",
            "صفحه خانه",
            "صفحه فرود",
            "لندینگ",
        ),
    )
    accessibility = _contains_any_term(normalized, ACCESSIBILITY_INTENT_TERMS)
    data_model = _requests_data_model_changes(normalized)
    file_frontend, file_backend = _file_role_signals(normalized)

    # ``table`` is a UI signal by default.  A schema/persistence signal turns
    # it into backend work only when no presentation language accompanies it.
    table_ui = _contains_any_term(
        normalized,
        (
            "table",
            "data table",
            "data grid",
            "datagrid",
            "grid",
            "جدول",
            "شبکه داده",
        ),
    )
    table_presentation = _contains_any_term(
        normalized,
        (
            "show",
            "display",
            "render",
            "list",
            "dashboard",
            "ui",
            "view",
            "screen",
            "نمایش",
            "لیست",
            "داشبورد",
            "رابط",
            "صفحه",
        ),
    )
    presentation_action_terms = (
        "show",
        "display",
        "render",
        "list",
        "نمایش",
        "نشان بده",
        "رندر",
        "لیست",
    )
    frontend_core = _contains_any_term(normalized, FRONTEND_INTENT_TERMS)
    if _contains_any_term(normalized, presentation_action_terms):
        # A backend report can say that a service must ``display`` real data;
        # that verb alone does not create a UI writer.  Require a concrete
        # presentation subject for action-only display language, while a
        # chart/table/form/image request remains frontend work.
        presentation_context = _contains_any_term(
            normalized,
            (
                "ui",
                "ux",
                "component",
                "page",
                "screen",
                "table",
                "data table",
                "grid",
                "record",
                "records",
                "chart",
                "graph",
                "dashboard",
                "form",
                "image",
                "images",
                "gallery",
                "profile",
                "accessibility",
                "wcag",
                "جدول",
                "سابقه",
                "سوابق",
                "رکورد",
                "نمودار",
                "گراف",
                "داشبورد",
                "فرم",
                "تصویر",
                "تصاویر",
                "گالری",
                "پروفایل",
                "دسترسی‌پذیری",
                "دسترسی پذیری",
            ),
        )
        non_action_frontend_terms = tuple(
            term
            for term in FRONTEND_INTENT_TERMS
            if term not in presentation_action_terms
        )
        frontend_core = presentation_context or _contains_any_term(
            normalized,
            non_action_frontend_terms,
        )
    frontend = frontend_core or file_frontend
    if table_ui and data_model and not table_presentation:
        # Do not turn "create database table" into an accidental UI task.
        frontend = frontend and not (
            _contains_any_term(normalized, ("table", "جدول"))
            and not _contains_any_term(
                normalized,
                tuple(
                    term
                    for term in FRONTEND_INTENT_TERMS
                    if term
                    not in {
                        "table",
                        "data table",
                        "data grid",
                        "datagrid",
                        "grid",
                        "جدول",
                        "جدول نمایش",
                        "شبکه داده",
                    }
                ),
            )
        )

    form_signal = _contains_any_term(
        normalized,
        ("form", "contact form", "فرم", "فرم تماس"),
    )
    auth_ui_signal = _contains_any_term(
        normalized,
        (
            "login",
            "log in",
            "sign in",
            "logout",
            "log out",
            "sign up",
            "signup",
            "register",
            "registration",
            "password reset",
            "ورود",
            "وارد شدن",
            "ثبت‌نام",
            "ثبت نام",
            "نام‌نویسی",
            "بازیابی رمز",
        ),
    )
    auth_signal = _contains_any_term(normalized, SECURITY_INTENT_TERMS)
    local_storage_only = _is_local_storage_only(normalized)
    payment_signal = _contains_any_term(
        normalized,
        (
            "checkout",
            "payment",
            "pay",
            "shopping cart checkout",
            "پرداخت",
            "درگاه",
            "سبد خرید و پرداخت",
            "خرید",
            "کارت بانکی",
        ),
    )
    cart_signal = _contains_any_term(
        normalized,
        ("cart", "shopping cart", "سبد خرید"),
    )
    upload_signal = _contains_any_term(
        normalized,
        (
            "upload",
            "file upload",
            "image upload",
            "آپلود",
            "بارگذاری فایل",
            "ارسال فایل",
        ),
    )
    seo_signal = _contains_any_term(
        normalized,
        (
            "seo",
            "metadata",
            "meta tags",
            "canonical",
            "structured data",
            "sitemap",
            "robots.txt",
            "سئو",
            "متادیتا",
            "متا تگ",
            "کنونیکال",
            "داده ساختاریافته",
            "نقشه سایت",
            "نقشهٔ سایت",
        ),
    )

    # Explicit security terms never include the generic Persian word
    # ``دسترسی``.  This is what prevents ``دسترسی‌پذیری`` from becoming a
    # security task while still routing ``امنیت و مجوز`` correctly.
    security = auth_signal
    backend = _contains_any_term(normalized, BACKEND_INTENT_TERMS) or file_backend
    if (
        _contains_any_term(normalized, ("save", "store", "persist", "persistence", "ذخیره"))
        and not local_storage_only
        and not _contains_any_term(
            normalized,
            (
                "button",
                "save button",
                "store button",
                "دکمه ذخیره",
                "دکمه ثبت",
            ),
        )
    ):
        backend = True
    if _contains_any_term(normalized, ("storage", "ذخیره‌سازی", "ذخیره سازی")) and not _contains_any_term(
        normalized,
        ("local storage", "localstorage", "browser storage", "ذخیره‌سازی محلی", "ذخیره سازی محلی"),
    ):
        backend = True
    if local_storage_only:
        # ``ذخیره‌سازی`` is a backend noun by itself, but browser/local
        # storage is a client-side concern until a server/API boundary is
        # explicitly requested.
        backend = False

    if form_signal:
        frontend = True
        if (_has_dynamic_data_signal(normalized) and not local_storage_only) or _contains_any_term(
            normalized,
            (
                "submit",
                "send",
                "email",
                "mail",
                "store response",
                "save response",
                "ارسال",
                "فرستادن",
                "ایمیل",
                "ذخیره پاسخ",
                "ثبت پاسخ",
            ),
        ):
            backend = True

    if auth_signal:
        backend = True
        security = True
    if auth_ui_signal:
        frontend = True
        backend = True
        security = True

    if payment_signal:
        frontend = True
        backend = True
        security = True
    elif cart_signal:
        frontend = True

    if upload_signal:
        frontend = True
        # A bare upload needs both an input and a receiving path.  A clearly
        # visual-only upload button/drag target stays frontend-only.
        if not _contains_any_term(
            normalized,
            ("upload button", "upload ui", "drag and drop", "دکمه آپلود", "رابط آپلود"),
        ) or _has_dynamic_data_signal(normalized):
            backend = True

    # Search, filtering, sorting, pagination, comments, and messaging are
    # presentation features by default.  They cross the server boundary only
    # when the request names a persistent/live source; this keeps a static
    # search box cheap while routing real data flows to a backend writer.
    collection_ui_signal = _contains_any_term(
        normalized,
        (
            "search",
            "search box",
            "search bar",
            "autocomplete",
            "filter",
            "filters",
            "sorting",
            "sort",
            "pagination",
            "infinite scroll",
            "جستجو",
            "جست‌وجو",
            "فیلتر",
            "مرتب‌سازی",
            "مرتب سازی",
            "صفحه‌بندی",
            "صفحه بندی",
            "اسکرول بی‌نهایت",
        ),
    )
    if collection_ui_signal:
        frontend = True
        if _has_dynamic_data_signal(normalized) or _contains_any_term(
            normalized,
            (
                "results",
                "records",
                "query",
                "database",
                "api",
                "server",
                "نتایج",
                "رکورد",
                "پایگاه داده",
                "جستجوی پایگاه داده",
            ),
        ):
            backend = True

    collaboration_ui_signal = _contains_any_term(
        normalized,
        (
            "comments",
            "comment",
            "reviews",
            "ratings",
            "rating",
            "نظرات",
            "نظر",
            "دیدگاه",
            "امتیاز",
        ),
    )
    if collaboration_ui_signal:
        frontend = True
        if not _contains_any_term(
            normalized,
            ("comment ui", "comment widget", "نمایش نظر", "ظاهر نظرات"),
        ):
            backend = True

    notification_signal = _contains_any_term(
        normalized,
        (
            "notification",
            "notifications",
            "email notification",
            "push notification",
            "toast",
            "alert",
            "اعلان",
            "پیام‌رسانی",
            "اعلان پوش",
        ),
    )
    if notification_signal:
        frontend = True
        if _contains_any_term(
            normalized,
            (
                "email",
                "mail",
                "push",
                "server",
                "api",
                "queue",
                "webhook",
                "ایمیل",
                "پوش",
                "سمت سرور",
            ),
        ):
            backend = True

    chat_signal = _contains_any_term(
        normalized,
        (
            "chat",
            "live chat",
            "messaging",
            "conversation",
            "websocket",
            "websockets",
            "چت",
            "گفتگو",
            "پیام‌رسانی",
        ),
    )
    if chat_signal:
        frontend = True
        if _has_dynamic_data_signal(normalized) or _contains_any_term(
            normalized,
            ("websocket", "websockets", "send", "receive", "live", "بلادرنگ", "ارسال", "دریافت"),
        ):
            backend = True

    account_or_admin_signal = _contains_any_term(
        normalized,
        (
            "admin panel",
            "user profile",
            "profile",
            "user roles",
            "role based permissions",
            "پنل مدیریت",
            "پروفایل کاربر",
            "نقش کاربری",
            "سطح دسترسی",
        ),
    )
    if account_or_admin_signal:
        frontend = True
        if _contains_any_term(
            normalized,
            (
                "admin panel",
                "user roles",
                "role based permissions",
                "auth",
                "permission",
                "database",
                "api",
                "server",
                "پنل مدیریت",
                "نقش کاربری",
                "سطح دسترسی",
            ),
        ):
            backend = True
            if _contains_any_term(
                normalized,
                (
                    "user roles",
                    "role based permissions",
                    "permission",
                    "نقش کاربری",
                    "سطح دسترسی",
                ),
            ):
                security = True

    commerce_or_reporting_signal = _contains_any_term(
        normalized,
        (
            "subscription",
            "subscriptions",
            "billing",
            "invoice",
            "invoicing",
            "analytics",
            "analytics tracking",
            "tracking",
            "csv export",
            "csv import",
            "pdf generation",
            "report generation",
            "pdf report",
            "generate report",
            "export report",
            "گزارش‌گیری",
            "گزارش گیری",
            "صورتحساب",
            "فاکتور",
            "اشتراک",
            "تحلیل رفتار",
            "ردیابی رویداد",
            "خروجی csv",
            "ورودی csv",
            "تولید pdf",
            "تولید گزارش",
            "گزارش pdf",
            "گزارش پی‌دی‌اف",
        ),
    )
    if commerce_or_reporting_signal:
        frontend = True
        backend = True

    if _contains_any_term(normalized, ("csv", "خروجی", "ورودی")) and _contains_any_term(
        normalized,
        ("export", "import", "خروجی", "ورودی", "فایل"),
    ):
        frontend = True
        if not _contains_any_term(
            normalized,
            ("export button", "import button", "دکمه خروجی", "دکمه ورودی"),
        ):
            backend = True

    security_boundary_signal = _contains_any_term(
        normalized,
        (
            "captcha",
            "rate limiting",
            "rate limit",
            "cors",
            "audit log",
            "audit trail",
            "کپچا",
            "محدودیت درخواست",
            "محدودسازی درخواست",
            "لاگ ممیزی",
            "گزارش ممیزی",
        ),
    )
    if security_boundary_signal:
        backend = True
        security = True
        if _contains_any_term(normalized, ("captcha", "کپچا")):
            frontend = True

    localization_signal = _contains_any_term(
        normalized,
        (
            "multilingual",
            "multi-language",
            "i18n",
            "translation",
            "rtl",
            "right to left",
            "چندزبانه",
            "ترجمه",
            "راست به چپ",
        ),
    )
    if localization_signal:
        frontend = True
        if _contains_any_term(
            normalized,
            ("translation api", "translation service", "locale database", "ذخیره ترجمه", "سرویس ترجمه"),
        ):
            backend = True

    # A service worker belongs to the browser application.  The generic word
    # ``service`` is also a server signal, so explicitly remove that false
    # backend route unless the ticket names a separate server boundary.
    if _contains_any_term(normalized, ("service worker", "سرویس‌ورکر", "سرویس ورکر")):
        frontend = True
        if not _contains_any_term(
            normalized,
            ("service worker api", "service worker server", "سرویس ورکر سمت سرور"),
        ):
            backend = False

    file_transfer_signal = _contains_any_term(
        normalized,
        (
            "file download",
            "download file",
            "download endpoint",
            "file export",
            "دانلود فایل",
            "خروجی فایل",
        ),
    )
    if file_transfer_signal:
        frontend = True
        if not _contains_any_term(
            normalized,
            ("download button", "download ui", "دکمه دانلود", "رابط دانلود"),
        ):
            backend = True

    if seo_signal:
        frontend = True
        if _contains_any_term(
            normalized,
            (
                "dynamic sitemap",
                "generate sitemap",
                "sitemap route",
                "sitemap api",
                "server-side seo",
                "route",
                "api",
                "server",
                "database",
                "نقشه سایت پویا",
                "تولید نقشه سایت",
                "مسیر نقشه سایت",
            ),
        ):
            backend = True

    # A chart/dashboard/table becomes backend work only when a live or
    # explicit data source is requested.  Static visualizations remain cheap
    # frontend tasks.
    if _contains_any_term(
        normalized,
        ("chart", "graph", "plot", "dashboard", "نمودار", "گراف", "داشبورد"),
    ) and _has_dynamic_data_signal(normalized):
        frontend = True
        backend = True

    if data_model:
        backend = True
        if table_presentation or _contains_any_term(
            normalized,
            ("dashboard", "chart", "graph", "form", "صفحه", "داشبورد", "نمودار", "فرم"),
        ):
            frontend = True

    release = _contains_any_term(normalized, RELEASE_INTENT_TERMS)
    # File names can identify a frontend target even when the user says only
    # "update App.tsx".  Conversely a service/controller name must not be
    # routed to the frontend because the suffix happens to be PHP/JS.
    if file_backend and not file_frontend:
        backend = True

    domains: list[AgentRole] = []
    for role, selected in (
        ("frontend", frontend),
        ("backend", backend),
        ("security", security),
        ("release", release),
    ):
        if selected:
            domains.append(role)  # type: ignore[arg-type]
    profile = IntentProfile(
        implementation=implementation,
        domains=tuple(domains),
        frontend=frontend,
        backend=backend,
        security=security,
        release=release,
        homepage=homepage,
        accessibility=accessibility,
        frontend_assets=(
            _contains_any_term(
                normalized,
                (
                    "css",
                    "stylesheet",
                    "style",
                    "layout",
                    "template",
                    "theme",
                    "font",
                    "typography",
                    "color",
                    "colour",
                    "asset",
                    "assets",
                    "image",
                    "images",
                    "icon",
                    "logo",
                    "navigation",
                    "nav",
                    "menu",
                    "header",
                    "footer",
                    "hero",
                    "banner",
                    "gallery",
                    "form",
                    "responsive",
                    "mobile",
                    "tablet",
                    "accessibility",
                    "accessible",
                    "wcag",
                    "a11y",
                    "seo",
                    "metadata",
                    "meta tags",
                    "sitemap",
                    "rtl",
                    "رابط کاربری",
                    "طراحی",
                    "چیدمان",
                    "قالب",
                    "استایل",
                    "تم",
                    "فونت",
                    "تایپوگرافی",
                    "رنگ",
                    "تصویر",
                    "تصاویر",
                    "آیکون",
                    "لوگو",
                    "ناوبری",
                    "منو",
                    "سربرگ",
                    "هدر",
                    "پانوشت",
                    "فوتر",
                    "هیرو",
                    "بنر",
                    "گالری",
                    "فرم",
                    "واکنش‌گرا",
                    "واکنش گرا",
                    "دسترسی‌پذیری",
                    "دسترسی پذیری",
                    "سئو",
                    "متادیتا",
                    "متا تگ",
                    "نقشه سایت",
                    "نقشهٔ سایت",
                    "راست به چپ",
                ),
            )
            or file_frontend
        ),
        data_model=data_model,
        explicit_files=_file_tokens(text),
    )
    profile.validate()
    return profile


def requests_implementation(text: str) -> bool:
    """Return whether bilingual ticket text clearly requests a real change."""

    if _contains_any_term(text, IMPLEMENTATION_ACTION_TERMS):
        return True

    # Persian tickets often put the action at the end of a sentence instead
    # of using one of the explicit verbs above, for example ``... را قابل
    # انتخاب کن`` (make ... selectable).  The old classifier treated the
    # trailing ``کن`` as ordinary prose, so a real implementation was routed
    # through the provider Discovery node first.  That extra node repeated
    # the same local Project Brain scan and could exhaust its fresh-token
    # allocation before a writer ever started.  Require an object marker (the
    # Persian ``را``/``رو`` or ``قابل`` construction) so an audit such as
    # ``بررسی کن`` remains read-only.
    normalized = _normalise_intent_text(text)
    if re.search(
        r"(?:^|\s)(?:[^\n؛.!؟]{0,120}\s)?(?:را|رو)\s+[^\n؛.!؟]{0,120}\b(?:کن|کنید|بکن|بکنید)\b",
        normalized,
    ):
        return True
    return bool(
        re.search(
            r"\bقابل\s+[^\n؛.!؟]{1,80}\b(?:کن|کنید|بکن|بکنید)\b",
            normalized,
        )
    )


def _has_explicit_file_scope(text: str) -> bool:
    """Detect a ticket that already names concrete files to change."""

    return bool(_file_tokens(text))


def _should_skip_discovery(
    task: ProductTask,
    risk: RiskLevel,
    likely_paths: tuple[str, ...],
) -> bool:
    """Skip redundant discovery only for small, explicitly scoped tickets."""

    text = " ".join(
        (task.title, task.objective, *task.requirements)
    ).casefold()
    discovery_terms = (
        "discover",
        "inspect",
        "understand",
        "analy",
        "audit",
        "architecture",
        "review",
        "بررسی",
        "تحلیل",
        "ممیزی",
        "معماری",
        "شناخت",
    )
    implementation_requested = (
        task.kind in {"bug_fix", "feature", "ui_improvement"}
        or requests_implementation(text)
    )
    recovery_context = any(
        item.strip().startswith(
            (
                "Recovery owner:",
                "Previous Empy execution failed",
                "Previous Empy verification findings",
                "علت قطعی شکست قبلی / Exact failing checks:",
            )
        )
        for item in task.constraints
    )
    # Project Brain and the bounded context selector already perform local,
    # deterministic discovery.  A provider discovery turn before every
    # implementation repeats the same scan, spends tokens, and cannot expand
    # the writer's approved ownership anyway.
    if implementation_requested and likely_paths:
        return True
    # A corrective task already carries a bounded, durable failure handoff
    # and the local Project Brain has the indexed scope.  Running a fresh
    # provider Discovery node here is both redundant and unsafe: if it burns
    # its allocation, the actual writer never receives a chance to repair the
    # confirmed file.  Recovery remains disabled for explicit audit tasks,
    # which have no writer contract to execute.
    if recovery_context and task.kind != "audit" and likely_paths:
        return True
    return (
        risk == "low"
        and bool(likely_paths)
        and _has_explicit_file_scope(text)
        and not any(term in text for term in discovery_terms)
    )


def _roles(
    task: ProductTask,
    risk: RiskLevel,
    *,
    include_discovery: bool = True,
    include_quality: bool = True,
) -> tuple[AgentRole, ...]:
    text = " ".join(
        (
            task.title,
            task.objective,
            *task.requirements,
        )
    )

    roles: list[AgentRole] = ["discovery"] if include_discovery else []

    # Audit tasks are explicitly read-only by contract.  Even if an audit
    # brief quotes an imperative such as "fix accessibility" as a
    # recommendation, it must never turn into a writer node.
    if task.kind == "audit":
        if include_quality:
            roles.append("quality")
        return tuple(dict.fromkeys(roles))

    profile = classify_intent(text)

    # Market/data words need a server role only when the request actually
    # asks for a data source, price calculation, or live feed.  "Update asset
    # images" is presentation-only; "live asset prices in a chart" crosses
    # the backend boundary.
    market_signal = _contains_any_term(
        text,
        (
            "price",
            "prices",
            "quote",
            "market",
            "finance",
            "financial",
            "portfolio",
            "قیمت",
            "بازار",
            "مالی",
            "دارایی",
        ),
    )
    visual_data_signal = _contains_any_term(
        text,
        (
            "chart",
            "graph",
            "plot",
            "dashboard",
            "table",
            "data",
            "نمودار",
            "گراف",
            "داشبورد",
            "جدول",
            "اطلاعات",
        ),
    )
    if market_signal and (
        visual_data_signal
        or _has_dynamic_data_signal(text)
        or _contains_any_term(text, ("add price", "show price", "قیمت واقعی", "قیمت لحظه‌ای", "قیمت لحظه ای"))
    ):
        profile = replace(
            profile,
            backend=True,
            domains=tuple(dict.fromkeys((*profile.domains, "backend"))),
        )
        profile.validate()

    for role in profile.domains:
        if role in {"frontend", "backend", "security", "release"}:
            roles.append(role)

    # The release template is an explicit product-level decision, even when
    # the brief itself contains no release keyword.
    if task.kind == "release":
        roles.append("release")

    # Natural-language custom tickets do not always contain a domain word
    # such as "backend" or "frontend".  Without a fallback, an actionable
    # ticket like "change the greeting and update its test" was reduced to
    # discovery + quality, so no agent could own a file.  Keep explicit
    # read-only/audit requests read-only, but route clear implementation
    # language to the backend writer as the generic code owner.  More
    # specific frontend/security/release roles above still win ownership by
    # their narrower patterns.
    if not set(roles) & {"frontend", "backend", "security", "release"} and (
        task.kind in {"bug_fix", "feature", "ui_improvement"}
        or requests_implementation(text)
    ):
        roles.append("backend")

    implementation_roles = {
        "frontend",
        "backend",
        "security",
        "release",
    }
    explicit_specialist_request = _contains_any_term(
        text,
        (
            "separate agents",
            "specialist agents",
            "independent agents",
            "ایجنت‌های جدا",
            "ایجنت متخصص",
            "نقش‌های جدا",
        ),
    )
    # Every provider process pays a large, mostly fixed harness cost. For a
    # low/medium-risk ticket that touches three or more domains, several
    # serial writer calls cost more than they save. Keep the specialist
    # ownership contract in the graph, but execute the implementation through
    # one bounded coordinator unless the ticket explicitly asks for separate
    # agents or the risk is high enough to justify the extra calls.
    if (
        len(set(roles) & implementation_roles) >= 3
        and risk != "high"
        and not explicit_specialist_request
    ):
        roles = [role for role in roles if role not in implementation_roles]
        roles.append("coordinator")

    if include_quality:
        roles.append("quality")
    return tuple(dict.fromkeys(roles))


def _has_deterministic_verification(project: ProjectDetection) -> bool:
    """Detect whether Empy can verify the project without a quality Agent."""

    root = project.effective_verification_root
    if project.descriptor.project_type == "node":
        try:
            value = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        scripts = value.get("scripts", {}) if isinstance(value, dict) else {}
        return isinstance(scripts, dict) and any(
            name in scripts for name in ("test", "build", "lint")
        )
    if project.descriptor.project_type == "python":
        return True
    if project.descriptor.project_type in {"php", "laravel", "rust", "go"}:
        return True
    return bool((root / ".empy" / "verification.json").is_file())


def _should_skip_provider_quality(
    task: ProductTask,
    project: ProjectDetection,
    risk: RiskLevel,
) -> bool:
    del risk
    text = " ".join((task.title, task.objective, *task.requirements)).casefold()
    implementation_requested = (
        task.kind in {"bug_fix", "feature", "ui_improvement"}
        or requests_implementation(text)
    )
    # Quality is an evidence phase, not a second language-model opinion.
    # Whenever Empy has a deterministic contract, run that contract locally
    # after the writer instead of paying a provider to describe checks that
    # Empy will run again.
    return implementation_requested and _has_deterministic_verification(project)


def _build_steps(
    task: ProductTask,
    roles: tuple[AgentRole, ...],
    risk: RiskLevel,
    estimated_files: int,
    *,
    include_discovery: bool = True,
    include_quality: bool = True,
) -> tuple[PlanStep, ...]:
    steps: list[PlanStep] = []
    if include_discovery:
        steps.append(
            PlanStep(
                step_id="discovery",
                title="Discover relevant project scope",
                objective=(
                    "Locate only the files and modules "
                    "required by this task."
                ),
                depends_on=(),
                suggested_agent="discovery",
                estimated_files=max(
                    1,
                    estimated_files // 2,
                ),
                risk="low",
            )
        )

    previous: str | None = "discovery" if include_discovery else None
    implementation_roles = tuple(
        role
        for role in roles
        if role not in {
            "discovery",
            "quality",
        }
    )

    for role in implementation_roles:
        step_id = f"implement-{role}"
        if previous is None:
            step_dependencies: tuple[str, ...] = ()
        else:
            step_dependencies = (previous,)
        steps.append(
            PlanStep(
                step_id=step_id,
                title=(
                    f"Implement {role} scope"
                ),
                objective=(
                    "Apply only the approved "
                    f"{role} changes."
                ),
                depends_on=step_dependencies,
                suggested_agent=role,
                estimated_files=max(
                    1,
                    estimated_files
                    // max(
                        1,
                        len(implementation_roles),
                    ),
                ),
                risk=risk,
            )
        )
        previous = step_id

    if include_quality:
        if previous is None:
            quality_dependencies: tuple[str, ...] = ()
        else:
            quality_dependencies = (previous,)
        steps.append(
            PlanStep(
                step_id="quality",
                title="Verify requested work",
                objective=(
                    "Run relevant checks and collect "
                    "evidence without publishing."
                ),
                depends_on=quality_dependencies,
                suggested_agent="quality",
                estimated_files=0,
                risk="low",
            )
        )
    return tuple(steps)


def generate_execution_plan(
    *,
    task: ProductTask,
    project: ProjectDetection,
) -> ExecutionPlan:
    task.validate()
    project.descriptor.validate()

    if task.status != "ready_for_planning":
        raise ValueError(
            "task must be ready_for_planning"
        )

    if (
        Path(task.project_root)
        .expanduser()
        .resolve()
        != project.descriptor.root
    ):
        raise ValueError(
            "task and project roots do not match"
        )

    likely_paths = _likely_paths(
        task,
        project,
    )
    risk = _risk(task, likely_paths)
    include_discovery = not _should_skip_discovery(
        task,
        risk,
        likely_paths,
    )
    include_quality = not _should_skip_provider_quality(task, project, risk)
    roles = _roles(
        task,
        risk,
        include_discovery=include_discovery,
        include_quality=include_quality,
    )

    # Do not manufacture a backend Agent merely because a PHP deployment also
    # contains index.php. Static homepage/navigation tickets are owned by the
    # frontend writer and may intentionally create index.html (for example
    # when DirectoryIndex selects it before index.php). Explicit API, route,
    # database, service, or server-side terms are already routed to backend by
    # _roles above. The old fallback doubled provider harness cost for a change
    # that needed only one file and one writer.

    base_files = (
        len(task.requirements)
        + len(likely_paths)
    )
    estimated_files = max(
        1,
        min(
            30,
            base_files,
        ),
    )
    estimated_tokens = max(
        4_000,
        min(
            120_000,
            (
                3_000
                + len(task.objective) * 8
                + sum(
                    len(item) * 8
                    for item in task.requirements
                )
                + estimated_files * 1_500
                + len(roles) * 2_000
            ),
        ),
    )
    steps = _build_steps(
        task,
        roles,
        risk,
        estimated_files,
        include_discovery=include_discovery,
        include_quality=include_quality,
    )

    fingerprint = _fingerprint_task(task)
    plan_id = hashlib.sha256(
        (
            task.task_id
            + fingerprint
            + project.descriptor.project_type
        ).encode("utf-8")
    ).hexdigest()[:20]

    plan = ExecutionPlan(
        schema_version=1,
        plan_id=plan_id,
        task_id=task.task_id,
        project_root=str(
            project.descriptor.root
        ),
        project_type=(
            project.descriptor.project_type
        ),
        status="draft",
        created_at=_utc_now(),
        approved_at=None,
        summary=(
            f"{len(steps)} planned steps using {len(roles)} suggested roles"
            + (
                "; deterministic Verification replaces a redundant Provider quality node"
                if not include_quality
                else ""
            )
        ),
        risk=risk,
        estimated_files=estimated_files,
        estimated_agents=len(roles),
        estimated_tokens=estimated_tokens,
        likely_paths=likely_paths,
        steps=steps,
        task_fingerprint=fingerprint,
    )
    plan.validate()
    return plan


def approve_execution_plan(
    plan: ExecutionPlan,
    *,
    current_task: ProductTask,
) -> ExecutionPlan:
    plan.validate()
    current_task.validate()

    if plan.status != "draft":
        raise ValueError(
            "only a draft plan can be approved"
        )
    if (
        _fingerprint_task(current_task)
        != plan.task_fingerprint
    ):
        raise ValueError(
            "task changed after plan generation"
        )

    approved = replace(
        plan,
        status="approved",
        approved_at=_utc_now(),
    )
    approved.validate()
    return approved


def cancel_execution_plan(
    plan: ExecutionPlan,
) -> ExecutionPlan:
    plan.validate()
    if plan.status == "approved":
        raise ValueError(
            "approved plans are immutable"
        )
    cancelled = replace(
        plan,
        status="cancelled",
    )
    cancelled.validate()
    return cancelled
