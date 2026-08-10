# راهنمای Empy Studio

Empy Studio یک چارچوب محلی و قابل ممیزی برای سازمان‌دهی کار نرم‌افزاری است.
قرارداد تسک، Context، شواهد، اعتبارسنجی، افزونه‌ها، مسیر Codex، مدیریت انتشار
و توزیع در یک ساختار منسجم نگهداری می‌شوند.

## نصب

برای توسعه:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install ".[dev]"
```

بررسی نصب:

```bash
./.venv/bin/empy --help
./.venv/bin/ruff check .
./.venv/bin/python -m mypy src
./.venv/bin/python -m pytest -q
```

برای کاربر نهایی باید از Installer مخصوص سیستم‌عامل استفاده شود و نیازی به
Clone کردن مخزن نیست.

## نخستین گردش کار

یک گردش کار کنترل‌شده با سه ورودی روشن آغاز می‌شود:

1. فایل `AGENTS.md` برای دستورالعمل‌های سطح پروژه.
2. قرارداد تسک برای هدف، محدودیت‌ها و معیارهای پذیرش.
3. Manifest اجرا برای تعریف وظایف و خروجی‌های مورد انتظار.

اجرای Manifest:

```bash
empy runtime run \
  --manifest runtime-manifest.json \
  --output-root outputs
```

پیش از پذیرش نتیجه، خروجی و Evidence را بررسی کن.

## فرمان‌های اصلی

```text
empy doctor
empy context
empy runtime
empy plugin
empy codex
empy release
empy distribution
```

برای مشاهده رابط معتبر هر فرمان از `--help` استفاده کن.

## گردش کار Codex

Adapter مربوط به Codex فقط Context لازم را آماده می‌کند و کل پروژه را در هر
نشست دوباره ارسال نمی‌کند. قرارداد تسک، خروجی، Evidence و وضعیت نشست ذخیره
می‌شوند. هنگام نبودن Codex یا پایان توکن، ادامه کار از مسیر دستی ممکن است.

## افزونه‌ها

افزونه‌ها دارای Manifest معتبر، فرمت بسته، Registry، Lifecycle Manager و
Package Manager هستند. عملیات نصب، ارتقا و Rollback باید تراکنشی باشد.

## ایمنی انتشار

انتشار فقط زمانی مجاز است که Working Tree تمیز باشد، Tag کنترل‌شده به Commit
درست اشاره کند، CI همان Commit سبز شده باشد، Artifactها با Index تطبیق داشته
باشند و تمام Gateهای Release Candidate پاس شده باشند.

از Working Tree اعتبارسنجی‌نشده مستقیماً انتشار انجام نده.

## توزیع

Installerهای نسخه اول برای این سیستم‌ها تولید می‌شوند:

```text
macOS ARM64
macOS x86_64
Linux ARM64
Linux x86_64
Windows x86_64
```

Installer پیش از نصب، سازگاری Python و SHA-256 را بررسی می‌کند و برنامه را
در Virtual Environment جداگانه نصب می‌کند. Uninstaller فقط مسیرهایی را حذف
می‌کند که در `install-state.json` ثبت شده‌اند.

## شواهد

هر گردش کار مرتبط با انتشار باید Evidence قابل پیگیری داشته باشد؛ شامل فرمان،
ورودی‌ها، مسیر خروجی، Return Code، Digestهای قطعی و تصمیم نهایی پاس یا رد.
