@extends('layouts.app')
@section('content')
<div class="card">
    <div class="row"><div><h2>{{ $project->name }}</h2><div class="muted">{{ $project->original_filename }} · workspace مستقل</div></div><a class="button secondary" href="{{ route('dashboard') }}">بازگشت</a></div>
    <div class="grid" style="margin-top:16px">
        <div><div class="muted">فایل‌های قابل بررسی</div><strong>{{ $project->manifest['total_files'] ?? 0 }}</strong></div>
        <div><div class="muted">stack</div><strong>{{ implode('، ', $project->detected_stack['frameworks'] ?? []) ?: 'ناشناخته' }}</strong></div>
        <div><div class="muted">entry point</div><strong><code>{{ implode(', ', $project->detected_stack['entry_points'] ?? []) ?: 'پیدا نشد' }}</code></strong></div>
    </div>
    @if(!config('empy.ollama.model') && !config('empy.openai_compatible.model'))
        <div class="flash error" style="margin-top:16px">Provider مدل تنظیم نشده است. Import و Planner محلی کار می‌کند، اما برای اجرای تغییر باید Ollama یا endpoint سازگار را در <code>.env</code> فعال کنید.</div>
    @endif
</div>
<div class="card">
    <h2>Ticket جدید</h2>
    <form method="post" action="{{ route('tickets.store', $project) }}">
        @csrf
        <label for="title">عنوان کوتاه</label>
        <input id="title" name="title" required placeholder="مثلاً تغییر متن صفحه اول">
        <label for="request_text">درخواست دقیق</label>
        <textarea id="request_text" name="request_text" required placeholder="مثلاً در public/index.html عنوان اصلی را به ... تغییر بده"></textarea>
        <div class="actions"><button type="submit">ساخت گراف کار</button></div>
    </form>
</div>
<div class="card">
    <div class="row"><h2>Ticketها</h2><span class="muted">تکرار کورکورانهٔ گراف در این صفحه مجاز نیست.</span></div>
    @forelse($project->tickets as $ticket)
        <div class="card" style="margin:12px 0;background:#fbfcfe">
            <div class="row"><div><h3>{{ $ticket->title }}</h3><div class="muted">{{ $ticket->created_at?->format('Y-m-d H:i') }}</div></div><span class="badge {{ $ticket->status }}">{{ $ticket->status }}</span></div>
            <p>{{ $ticket->request_text }}</p>
            @if($ticket->failure_detail)<div class="flash error"><strong>علت:</strong> {{ $ticket->failure_detail }}</div>@endif
            @if($ticket->plan)
                <details><summary>گراف تأییدشده و فایل مالک</summary><pre>{{ json_encode(['fingerprint' => $ticket->plan_fingerprint, 'nodes' => $ticket->plan['nodes'] ?? []], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) }}</pre></details>
            @endif
            <div class="actions">
                @if($ticket->status === 'planned')
                    <form method="post" action="{{ route('tickets.execute', $ticket) }}">@csrf<button type="submit">اجرای Agent</button></form>
                @elseif($ticket->status === 'executed')
                    <form method="post" action="{{ route('tickets.verify', $ticket) }}">@csrf<button class="success" type="submit">Verification</button></form>
                @elseif($ticket->status === 'verified')
                    <form method="post" action="{{ route('tickets.deliver', $ticket) }}">@csrf<button class="success" type="submit">ساخت ZIP نهایی</button></form>
                @elseif($ticket->status === 'delivered' && ($ticket->result['artifact_id'] ?? null))
                    <a class="button success" href="{{ route('artifacts.download', $ticket->result['artifact_id']) }}">دانلود ZIP</a>
                @endif
            </div>
        </div>
    @empty
        <div class="empty">هنوز Ticketی ثبت نشده است.</div>
    @endforelse
</div>
@endsection
