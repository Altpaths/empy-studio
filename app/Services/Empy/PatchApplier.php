<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyExecutionException;
use App\Models\Project;
use App\Support\Empy\PathGuard;
use Illuminate\Support\Facades\Storage;

final class PatchApplier
{
    public function __construct(private readonly PathGuard $paths)
    {
    }

    /** @return list<array{path: string, existed: bool, before: ?string, after: string}> */
    public function apply(Project $project, array $node, ProviderResponse $response): array
    {
        $writer = $this->paths->normalize((string) ($node['writer'] ?? ''));
        $root = Storage::disk($project->source_disk)->path($project->source_path);
        $changes = [];
        foreach ($response->files as $file) {
            $path = $this->paths->normalize($file['path']);
            if ($path !== $writer) {
                throw new EmpyExecutionException(
                    "Provider attempted to write {$path}; assigned writer is {$writer}.",
                    'out_of_scope_write',
                );
            }
            $target = $this->paths->join($root, $path);
            if (is_link($target)) {
                throw new EmpyExecutionException("Refusing to write through symlink {$path}.", 'unsafe_target');
            }
            $existed = is_file($target);
            $before = $existed ? file_get_contents($target) : null;
            if ($existed && $before === false) {
                throw new EmpyExecutionException("Could not read {$path} before writing.", 'read_before_write_failed');
            }
            if ($existed && $before === $file['content']) {
                continue;
            }
            $parent = dirname($target);
            if (!is_dir($parent) && !mkdir($parent, 0750, true) && !is_dir($parent)) {
                throw new EmpyExecutionException("Could not create the parent directory for {$path}.", 'write_failed');
            }
            $temporary = tempnam($parent, '.empy-write-');
            if ($temporary === false || file_put_contents($temporary, $file['content'], LOCK_EX) === false) {
                throw new EmpyExecutionException("Could not write {$path}.", 'write_failed');
            }
            chmod($temporary, 0640);
            if (!rename($temporary, $target)) {
                @unlink($temporary);
                throw new EmpyExecutionException("Could not commit {$path}.", 'write_failed');
            }
            $changes[] = [
                'path' => $path,
                'existed' => $existed,
                'before' => $before,
                'after' => hash('sha256', $file['content']),
            ];
        }

        return $changes;
    }

    /** @param list<array{path: string, existed: bool, before: ?string, after: string}> $changes */
    public function rollback(Project $project, array $changes): void
    {
        $root = Storage::disk($project->source_disk)->path($project->source_path);
        foreach (array_reverse($changes) as $change) {
            $target = $this->paths->join($root, $change['path']);
            if ($change['existed']) {
                file_put_contents($target, (string) $change['before'], LOCK_EX);
                continue;
            }
            if (is_file($target)) {
                unlink($target);
            }
        }
    }
}
