<!doctype html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ $title ?? 'Empy Studio' }}</title>
    <style>
        :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fb; color: #172033; }
        body { margin: 0; }
        .wrap { max-width: 980px; margin: 0 auto; padding: 32px 18px 64px; }
        h1, h2, h3 { margin: 0 0 12px; }
        h1 { font-size: 28px; }
        h2 { font-size: 20px; }
        p { line-height: 1.8; }
        .muted { color: #667085; font-size: 14px; }
        .card { background: #fff; border: 1px solid #e4e7ec; border-radius: 14px; padding: 20px; margin: 16px 0; box-shadow: 0 4px 16px #1720330a; }
        .grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
        label { display: block; font-weight: 600; margin: 12px 0 6px; }
        input, textarea { box-sizing: border-box; width: 100%; border: 1px solid #d0d5dd; border-radius: 9px; padding: 10px 12px; font: inherit; }
        textarea { min-height: 110px; resize: vertical; }
        button, .button { display: inline-block; border: 0; border-radius: 9px; background: #2563eb; color: white; padding: 10px 15px; font: inherit; cursor: pointer; text-decoration: none; }
        button.secondary, .button.secondary { background: #eef2ff; color: #1d4ed8; }
        button.success, .button.success { background: #15803d; }
        button.warn { background: #b45309; }
        .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
        .flash { border-radius: 10px; padding: 12px 14px; margin: 12px 0; }
        .flash.success { background: #ecfdf3; color: #166534; border: 1px solid #bbf7d0; }
        .flash.error { background: #fff1f2; color: #9f1239; border: 1px solid #fecdd3; }
        .badge { display: inline-block; border-radius: 999px; padding: 4px 9px; background: #eef2ff; color: #3730a3; font-size: 12px; }
        .badge.failed { background: #fff1f2; color: #9f1239; }
        .badge.verified, .badge.delivered, .badge.succeeded { background: #ecfdf3; color: #166534; }
        .row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
        code, pre { direction: ltr; text-align: left; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
        pre { background: #101828; color: #e4e7ec; border-radius: 10px; padding: 12px; overflow: auto; font-size: 12px; }
        details { margin-top: 12px; }
        .empty { padding: 28px; text-align: center; color: #667085; }
    </style>
</head>
<body>
<div class="wrap">
    <div class="row" style="margin-bottom: 20px">
        <a href="{{ route('dashboard') }}" style="text-decoration:none;color:inherit"><h1>Empy Studio</h1></a>
        <span class="muted">نسخه {{ config('empy.version') }} · پروژه ← Ticket ← اجرا ← Verification ← ZIP</span>
    </div>
    @if(session('success')) <div class="flash success">{{ session('success') }}</div> @endif
    @if(session('error')) <div class="flash error">{{ session('error') }}</div> @endif
    @yield('content')
</div>
</body>
</html>
