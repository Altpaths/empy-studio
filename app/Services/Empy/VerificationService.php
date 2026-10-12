<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyVerificationException;
use App\Models\Ticket;
use Illuminate\Support\Facades\Storage;
use Symfony\Component\Process\Process;

final class VerificationService
{
    public function __construct(private readonly ProjectIndexer $indexer) {}

    /** @return array{changed_files: list<string>, checks: list<array<string, mixed>>, verified_at: string} */
    public function verify(Ticket $ticket): array
    {
        $retryableVerificationFailure = $ticket->status === 'failed'
            && $ticket->failure_code === 'verification_error'
            && is_array($ticket->result)
            && ($ticket->result['changed_files'] ?? []) !== [];
        if (($ticket->status !== 'executed' && ! $retryableVerificationFailure) || ! is_array($ticket->result)) {
            throw new EmpyVerificationException('Ticket must finish execution before verification.', 'execution_required');
        }
        $project = $ticket->project;
        $root = Storage::disk($project->source_disk)->path($project->source_path);
        $current = $this->indexer->index($root);
        $baseline = is_array($ticket->baseline_manifest)
            ? $ticket->baseline_manifest
            : ($project->manifest ?? []);
        $before = array_column($baseline['files'] ?? [], 'sha256', 'path');
        $after = array_column($current['files'], 'sha256', 'path');
        $declared = array_fill_keys($ticket->result['changed_files'] ?? [], true);
        if ($declared === []) {
            throw new EmpyVerificationException('The execution report contains no changed file.', 'no_project_change');
        }
        $actual = [];
        foreach ($after as $path => $hash) {
            if (! isset($before[$path]) || $before[$path] !== $hash) {
                $actual[] = $path;
            }
        }
        foreach ($before as $path => $hash) {
            if (! isset($after[$path])) {
                throw new EmpyVerificationException("File {$path} disappeared outside the approved patch.", 'unexpected_file_deletion');
            }
        }
        $unexpected = array_values(array_diff($actual, array_keys($declared)));
        if ($unexpected !== []) {
            throw new EmpyVerificationException(
                'Files outside the approved writer changed: '.implode(', ', $unexpected),
                'out_of_scope_change',
            );
        }
        $missing = array_values(array_diff(array_keys($declared), $actual));
        if ($missing !== []) {
            throw new EmpyVerificationException(
                'The requested writer did not produce a project diff: '.implode(', ', $missing),
                'no_project_change',
            );
        }

        $checks = [];
        foreach ($actual as $path) {
            $absolute = Storage::disk($project->source_disk)->path($project->source_path.'/'.$path);
            $checks[] = ['path' => $path, 'check' => 'exists', 'passed' => is_file($absolute)];
            if (! is_file($absolute)) {
                throw new EmpyVerificationException("Verified file {$path} is missing.", 'verification_file_missing');
            }
            $extension = strtolower(pathinfo($path, PATHINFO_EXTENSION));
            if ($extension === 'php') {
                $process = new Process(['php', '-l', $absolute]);
                $process->run();
                $checks[] = ['path' => $path, 'check' => 'php_syntax', 'passed' => $process->isSuccessful()];
                if (! $process->isSuccessful()) {
                    throw new EmpyVerificationException("PHP syntax verification failed for {$path}.", 'syntax_failed');
                }
            } elseif ($extension === 'json') {
                $decoded = json_decode((string) file_get_contents($absolute), true);
                $checks[] = ['path' => $path, 'check' => 'json_syntax', 'passed' => json_last_error() === JSON_ERROR_NONE];
                if (json_last_error() !== JSON_ERROR_NONE) {
                    throw new EmpyVerificationException("JSON syntax verification failed for {$path}.", 'syntax_failed');
                }
            }
        }

        $result = [
            'changed_files' => array_values($actual),
            'checks' => $checks,
            'verified_at' => now()->toIso8601String(),
        ];
        $project->update([
            'manifest' => $current,
            'detected_stack' => [
                'frameworks' => $current['frameworks'],
                'entry_points' => $current['entry_points'],
            ],
        ]);
        $ticket->update([
            'status' => 'verified',
            'result' => array_merge($ticket->result, ['verification' => $result]),
            'failure_code' => null,
            'failure_detail' => null,
        ]);

        return $result;
    }
}
