<?php

namespace App\Http\Controllers;

use App\Exceptions\EmpyExecutionException;
use App\Exceptions\EmpyVerificationException;
use App\Models\Artifact;
use App\Models\Project;
use App\Models\Ticket;
use App\Services\Empy\DeliveryService;
use App\Services\Empy\ExecutionService;
use App\Services\Empy\RecoveryService;
use App\Services\Empy\TicketPlanner;
use App\Services\Empy\VerificationService;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Storage;

class TicketController extends Controller
{
    public function store(Request $request, Project $project, TicketPlanner $planner): RedirectResponse
    {
        $data = $request->validate([
            'title' => ['required', 'string', 'max:160'],
            'request_text' => ['required', 'string', 'max:12000'],
        ]);
        $ticket = $project->tickets()->create($data);
        try {
            $planner->plan($ticket->fresh('project'));
        } catch (\Throwable $exception) {
            $ticket->update(['status' => 'failed', 'failure_code' => $exception instanceof EmpyExecutionException ? $exception->errorCode : 'planning_failed', 'failure_detail' => $exception->getMessage()]);

            return back()->with('error', 'Ticket قابل برنامه‌ریزی نیست: '.$exception->getMessage());
        }

        return back()->with('success', 'گراف کار ساخته شد؛ فایل مالک و مسیر اجرای آن مشخص است. حالا «اجرا» را بزنید.');
    }

    public function execute(Ticket $ticket, ExecutionService $execution, RecoveryService $recovery): RedirectResponse
    {
        $run = $execution->execute($ticket->fresh('project'));
        $recovered = 0;
        while ($run->status !== 'succeeded' && $recovered < 3
            && $recovery->prepareNextAttempt($ticket->fresh('project'), $run)) {
            $recovered++;
            $run = $execution->execute($ticket->fresh('project'));
        }
        $ticket = $ticket->fresh();
        if ($run->status !== 'succeeded') {
            return back()->with('error', $this->executionError($ticket));
        }

        $message = 'تغییر واقعی در فایل‌های تعیین‌شده ایجاد شد. حالا Verification را اجرا کنید.';
        if ($recovered > 0) {
            $message = "بعد از {$recovered} recovery با graph متفاوت، تغییر واقعی ایجاد شد. حالا Verification را اجرا کنید.";
        }

        return back()->with('success', $message);
    }

    public function verify(Ticket $ticket, VerificationService $verification): RedirectResponse
    {
        try {
            $result = $verification->verify($ticket->fresh('project'));
        } catch (EmpyVerificationException $exception) {
            $ticket->update(['status' => 'failed', 'failure_code' => $exception->errorCode, 'failure_detail' => $exception->getMessage()]);

            return back()->with('error', 'Verification شکست خورد: '.$exception->getMessage());
        } catch (\Throwable $exception) {
            $ticket->update(['status' => 'failed', 'failure_code' => 'verification_error', 'failure_detail' => $exception->getMessage()]);

            return back()->with('error', 'Verification انجام نشد: '.$exception->getMessage());
        }

        return back()->with('success', 'Verification پاس شد: '.count($result['changed_files']).' فایل تغییر معتبر دارد. حالا ZIP را بسازید.');
    }

    public function deliver(Ticket $ticket, DeliveryService $delivery): RedirectResponse
    {
        try {
            $artifact = $delivery->deliver($ticket->fresh('project'));
        } catch (EmpyVerificationException $exception) {
            return back()->with('error', 'تحویل ZIP انجام نشد: '.$exception->getMessage());
        } catch (\Throwable $exception) {
            return back()->with('error', 'تحویل ZIP انجام نشد: '.$exception->getMessage());
        }

        return back()->with('success', 'ZIP نهایی ساخته شد و checksum آن ثبت شد.')->with('artifact_id', $artifact->id);
    }

    public function download(Artifact $artifact)
    {
        abort_unless(Storage::disk($artifact->disk)->exists($artifact->path), 404);

        return Storage::disk($artifact->disk)->download($artifact->path, basename($artifact->path));
    }

    private function executionError(Ticket $ticket): string
    {
        return match ($ticket->failure_code) {
            'provider_unavailable' => 'Provider آماده نیست. یک مدل Ollama یا endpoint سازگار را در تنظیمات فعال کنید.',
            'all_providers_failed' => 'همهٔ Providerهای تنظیم‌شده شکست خوردند؛ جزئیات تلاش‌ها در گزارش همین Ticket ثبت شده است.',
            'no_project_change' => 'هیچ فایل پروژه‌ای تغییر نکرد؛ برنامه همان گراف را کورکورانه تکرار نکرده است.',
            'out_of_scope_write' => 'Provider خواست خارج از فایل مالک بنویسد؛ تغییر برای حفاظت از پروژه rollback شد.',
            default => 'اجرا متوقف شد: '.($ticket->failure_detail ?: 'علت مشخصی ثبت نشده است.'),
        };
    }
}
