@extends('layouts.app')
@section('content')
<div class="card">
    <h2>پروژهٔ جدید</h2>
    <p class="muted">یک ZIP بدهید. Empy آن را در workspace مستقل باز می‌کند و فایل‌های پروژه‌های قبلی را وارد نمی‌کند.</p>
    <form id="project-import-form" method="post" action="{{ route('projects.store') }}" enctype="multipart/form-data">
        @csrf
        <label for="name">نام اختیاری پروژه</label>
        <input id="name" name="name" value="{{ old('name') }}" placeholder="مثلاً سایت اصلی">
        <label for="archive">فایل ZIP پروژه</label>
        <input id="archive" type="file" name="archive" accept=".zip" required
            oninvalid="this.setCustomValidity('لطفاً ابتدا فایل ZIP پروژه را انتخاب کنید.')"
            oninput="this.setCustomValidity('')">
        <p class="muted">اگر فایل روی iCloud یا Desktop به‌صورت ابری است، ابتدا آن را در Downloads کپی کنید تا کامل روی دستگاه خوانده شود.</p>
        @error('archive') <p class="flash error">{{ $message }}</p> @enderror
        <p id="archive-status" class="muted" role="status" aria-live="polite"></p>
        <div class="actions"><button id="project-import-submit" type="submit">وارد کردن پروژه</button></div>
    </form>
</div>
<div class="card">
    <div class="row"><h2>پروژه‌ها</h2><span class="muted">هر پروژه workspace و حافظهٔ جدا دارد.</span></div>
    @forelse($projects as $project)
        <div class="card" style="margin:12px 0;background:#fbfcfe">
            <div class="row"><div><h3>{{ $project->name }}</h3><div class="muted">{{ $project->manifest['total_files'] ?? 0 }} فایل · {{ $project->tickets_count }} Ticket</div></div><a class="button secondary" href="{{ route('projects.show', $project) }}">باز کردن</a></div>
            <p class="muted">{{ implode('، ', $project->detected_stack['frameworks'] ?? []) ?: 'stack ناشناخته' }}</p>
        </div>
    @empty
        <div class="empty">هنوز پروژه‌ای وارد نشده است.</div>
    @endforelse
</div>
<script>
(() => {
    const form = document.getElementById('project-import-form');
    const input = document.getElementById('archive');
    const submit = document.getElementById('project-import-submit');
    const status = document.getElementById('archive-status');
    if (!form || !input || !submit || !status) return;

    const maxBytes = 100 * 1024 * 1024;
    const chunkBytes = 1024 * 1024;
    const chunkTimeoutMs = 10000;
    const submitTimeoutMs = 90000;

    const setStatus = (message, error = false) => {
        status.textContent = message;
        status.className = error ? 'flash error' : 'muted';
    };

    const readChunk = (file, start, end) => new Promise((resolve, reject) => {
        const reader = new FileReader();
        let timer = window.setTimeout(() => {
            reader.abort();
            reject(new Error('خواندن فایل از سیستم بیش از حد طول کشید.'));
        }, chunkTimeoutMs);
        reader.onload = () => {
            window.clearTimeout(timer);
            resolve(new Uint8Array(reader.result));
        };
        reader.onerror = () => {
            window.clearTimeout(timer);
            reject(new Error('فایل از مسیر فعلی قابل خواندن نیست؛ آن را از iCloud یا Desktop به پوشهٔ Downloads کپی کنید و دوباره انتخاب کنید.'));
        };
        reader.onabort = () => {
            window.clearTimeout(timer);
            reject(new Error('خواندن فایل کامل نشد؛ آن را از iCloud یا Desktop به پوشهٔ Downloads کپی کنید و دوباره انتخاب کنید.'));
        };
        reader.readAsArrayBuffer(file.slice(start, end));
    });

    const isZip = (bytes) => bytes.length >= 4
        && bytes[0] === 0x50 && bytes[1] === 0x4b
        && (bytes[2] === 0x03 || bytes[2] === 0x05 || bytes[2] === 0x07)
        && (bytes[3] === 0x04 || bytes[3] === 0x06 || bytes[3] === 0x08);

    const preflight = async (file) => {
        if (!file) throw new Error('لطفاً ابتدا فایل ZIP پروژه را انتخاب کنید.');
        if (!/\.zip$/i.test(file.name)) throw new Error('فایل انتخاب‌شده ZIP نیست.');
        if (file.size === 0) throw new Error('فایل انتخاب‌شده خالی است.');
        if (file.size > maxBytes) throw new Error('حجم فایل از سقف امن ۱۰۰ مگابایت بیشتر است.');

        setStatus('در حال بررسی خوانا بودن فایل…');
        const firstChunk = await readChunk(file, 0, Math.min(chunkBytes, file.size));
        if (!isZip(firstChunk)) throw new Error('ساختار فایل ZIP قابل تشخیص نیست.');

        // Read every chunk before submitting. This catches cloud placeholders and
        // disconnected external volumes before the browser can navigate away.
        for (let start = 0; start < file.size; start += chunkBytes) {
            await readChunk(file, start, Math.min(start + chunkBytes, file.size));
            const percent = Math.min(100, Math.round(((start + chunkBytes) / file.size) * 100));
            setStatus(`فایل خوانده شد؛ ${percent}٪`);
        }
    };

    input.addEventListener('change', () => {
        status.textContent = '';
        status.className = 'muted';
    });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (submit.disabled) return;
        submit.disabled = true;
        try {
            const file = input.files && input.files[0];
            await preflight(file);
            setStatus('فایل آماده است؛ در حال وارد کردن پروژه…');
            const payload = new FormData(form);
            input.disabled = true;

            const controller = new AbortController();
            const timeout = window.setTimeout(() => controller.abort(), submitTimeoutMs);
            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    body: payload,
                    credentials: 'same-origin',
                    redirect: 'follow',
                    signal: controller.signal,
                });
                window.clearTimeout(timeout);
                if (!response.ok) throw new Error(`سرور با وضعیت ${response.status} پاسخ داد.`);
                window.location.assign(response.url);
            } catch (error) {
                window.clearTimeout(timeout);
                throw error;
            }
        } catch (error) {
            const message = error && error.name === 'AbortError'
                ? 'ارسال فایل بیش از ۹۰ ثانیه طول کشید و برای جلوگیری از صفحهٔ خطا متوقف شد. فایل را از iCloud یا Desktop به Downloads کپی کنید و دوباره انتخاب کنید.'
                : (error && error.message ? error.message : 'خواندن یا وارد کردن فایل انجام نشد.');
            setStatus(message, true);
            submit.disabled = false;
            input.disabled = false;
        }
    });
})();
</script>
@endsection
