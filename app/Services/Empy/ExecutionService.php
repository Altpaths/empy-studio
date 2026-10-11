<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyExecutionException;
use App\Exceptions\EmpyProviderException;
use App\Models\Run;
use App\Models\Ticket;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\Storage;

final class ExecutionService
{
    public function __construct(
        private readonly ContextLedger $context,
        private readonly ProviderManager $providers,
        private readonly PatchApplier $patches,
    ) {}

    public function execute(Ticket $ticket): Run
    {
        if ($ticket->status !== 'planned' || ! is_array($ticket->plan)) {
            throw new EmpyExecutionException('Ticket must have a validated plan before execution.', 'plan_required');
        }
        $plan = $ticket->plan;
        $attempt = ((int) $ticket->attempts) + 1;
        $run = Run::create([
            'ticket_id' => $ticket->id,
            'attempt' => $attempt,
            'status' => 'running',
            'graph_fingerprint' => $plan['fingerprint'] ?? null,
            'started_at' => Carbon::now(),
        ]);
        $ticket->update(['status' => 'running', 'attempts' => $attempt, 'started_at' => Carbon::now()]);
        $run->events()->create(['kind' => 'run_started', 'message' => 'Execution started with a validated graph.']);
        $applied = [];
        $providers = [];
        try {
            $context = $this->context->build($ticket->project, $plan);
            $run->update(['context_stats' => $context['stats']]);
            $run->events()->create([
                'kind' => 'context_built',
                'message' => 'Only unique planned files entered provider context.',
                'payload' => $context['stats'],
            ]);
            foreach ($plan['nodes'] as $node) {
                $nodeItems = $context['items_by_node'][$node['id']] ?? [];
                $providerRun = $this->providers->execute([
                    'messages' => $this->messages($ticket, $node, $nodeItems),
                    'workspace_path' => Storage::disk($ticket->project->source_disk)->path($ticket->project->source_path),
                ]);
                $providers[] = $providerRun->provider;
                $run->events()->create([
                    'kind' => 'provider_attempts',
                    'message' => 'Provider routing completed for '.$node['id'].'.',
                    'payload' => ['attempts' => $providerRun->attempts, 'provider' => $providerRun->provider],
                ]);
                $changes = $this->patches->apply($ticket->project, $node, $providerRun->response);
                $applied = array_merge($applied, $changes);
                if ($changes === []) {
                    throw new EmpyExecutionException('Provider returned content identical to the project; no project file changed.', 'no_project_change');
                }
            }
            if ($applied === []) {
                throw new EmpyExecutionException('Execution completed without a project change.', 'no_project_change');
            }
            $result = [
                'changed_files' => array_values(array_unique(array_column($applied, 'path'))),
                'providers' => array_values(array_unique($providers)),
                'context_stats' => $context['stats'],
            ];
            $run->update(['status' => 'succeeded', 'provider' => implode(',', array_unique($providers)), 'finished_at' => Carbon::now()]);
            $run->events()->create(['kind' => 'run_succeeded', 'message' => 'Execution produced a file diff.', 'payload' => $result]);
            $ticket->update(['status' => 'executed', 'result' => $result, 'failure_code' => null, 'failure_detail' => null, 'finished_at' => Carbon::now()]);
        } catch (EmpyProviderException $exception) {
            $this->patches->rollback($ticket->project, $applied);
            $this->fail($ticket, $run, $exception->errorCode, $exception->getMessage(), ['attempts' => $exception->attempts]);
        } catch (EmpyExecutionException $exception) {
            $this->patches->rollback($ticket->project, $applied);
            $this->fail($ticket, $run, $exception->errorCode, $exception->getMessage());
        } catch (\Throwable $exception) {
            $this->patches->rollback($ticket->project, $applied);
            $this->fail($ticket, $run, 'unexpected_execution_error', 'Execution stopped safely: '.$exception->getMessage());
        }

        return $run->fresh();
    }

    /** @param list<array<string, mixed>> $items @return list<array<string, string>> */
    private function messages(Ticket $ticket, array $node, array $items): array
    {
        $context = collect($items)->map(fn (array $item): string => "FILE: {$item['path']}\n{$item['content']}")->implode("\n\n---\n\n");
        $recoveryHint = is_string($ticket->plan['recovery_hint'] ?? null) ? "\nRecovery instruction: {$ticket->plan['recovery_hint']}" : '';

        return [
            [
                'role' => 'system',
                'content' => 'Return only JSON with this shape: {"summary":"...","files":[{"path":"assigned path","content":"complete file content"}],"context_summary":"optional"}. Never write outside the assigned writer path. Preserve unrelated content.',
            ],
            [
                'role' => 'user',
                'content' => "Objective: {$ticket->request_text}\nAssigned role: {$node['role']}\nAssigned writer: {$node['writer']}\nAction: {$node['action']}{$recoveryHint}\nCurrent context:\n{$context}",
            ],
        ];
    }

    /** @param array<string, mixed> $payload */
    private function fail(Ticket $ticket, Run $run, string $code, string $detail, array $payload = []): void
    {
        $run->update(['status' => 'failed', 'failure_code' => $code, 'failure_detail' => $detail, 'finished_at' => Carbon::now()]);
        $run->events()->create(['kind' => 'run_failed', 'message' => $detail, 'payload' => ['code' => $code] + $payload]);
        $ticket->update(['status' => 'failed', 'failure_code' => $code, 'failure_detail' => $detail, 'finished_at' => Carbon::now()]);
    }
}
