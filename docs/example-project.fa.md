# پروژه نمونه

این نمونه، کوچک‌ترین گردش کار کامل Empy Studio در نسخه اول را نشان می‌دهد.

## ساختار

```text
examples/v1-sample-project/
  AGENTS.md
  README.md
  task-contract.json
  runtime-manifest.json
  input/
    customer-request.md
```

فایل `AGENTS.md` قواعد کار را تعیین می‌کند. قرارداد تسک، هدف و معیار پذیرش را
تعریف می‌کند و Manifest اجرا، وظیفه را به خروجی و Evidence متصل می‌سازد.

## اجرا

از داخل پوشه پروژه نمونه:

```bash
empy runtime run \
  --manifest runtime-manifest.json \
  --output-root outputs
```

این سناریو محلی است و به دسترسی شبکه نیاز ندارد.

## شواهد مورد انتظار

اجرای موفق باید این فایل‌ها را ایجاد و نگهداری کند:

```text
outputs/result.json
outputs/evidence.json
```

Evidence باید شناسه تسک، ورودی‌ها، فرمان اجراشده، مسیر خروجی و وضعیت نهایی را
ثبت کند.

## بازبینی

صفر بودن Return Code به‌تنهایی کافی نیست. معیارهای پذیرش و وجود خروجی‌های
اعلام‌شده نیز باید بررسی شوند.
