@extends('layouts.app')
@section('content')
<div class="card">
    <h2>پروژهٔ جدید</h2>
    <p class="muted">یک ZIP بدهید. Empy آن را در workspace مستقل باز می‌کند و فایل‌های پروژه‌های قبلی را وارد نمی‌کند.</p>
    <form method="post" action="{{ route('projects.store') }}" enctype="multipart/form-data">
        @csrf
        <label for="name">نام اختیاری پروژه</label>
        <input id="name" name="name" value="{{ old('name') }}" placeholder="مثلاً سایت اصلی">
        <label for="archive">فایل ZIP پروژه</label>
        <input id="archive" type="file" name="archive" accept=".zip" required>
        @error('archive') <p class="flash error">{{ $message }}</p> @enderror
        <div class="actions"><button type="submit">وارد کردن پروژه</button></div>
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
@endsection
