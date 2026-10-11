<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyPlanningException;
use App\Models\Project;
use App\Support\Empy\PathGuard;

final class AgentPlanValidator
{
    public function __construct(private readonly PathGuard $paths)
    {
    }

    /** @param array<string, mixed> $plan */
    public function validate(Project $project, array $plan): array
    {
        $manifest = $project->manifest ?? [];
        $known = array_fill_keys(array_column($manifest['files'] ?? [], 'path'), true);
        $writers = [];
        foreach (($plan['nodes'] ?? []) as $node) {
            $nodeId = (string) ($node['id'] ?? 'unknown');
            $writer = (string) ($node['writer'] ?? '');
            if ($writer === '') {
                throw new EmpyPlanningException("Agent node {$nodeId} has no writable target.", 'missing_writer');
            }
            try {
                $writer = $this->paths->normalize($writer);
            } catch (\Throwable $exception) {
                throw new EmpyPlanningException("Agent node {$nodeId} has an invalid writable target.", 'invalid_writer');
            }
            if (isset($writers[$writer])) {
                throw new EmpyPlanningException("Two agents own {$writer}; one writer is required.", 'duplicate_writer');
            }
            $action = (string) ($node['action'] ?? 'modify');
            if (!isset($known[$writer]) && $action !== 'create') {
                throw new EmpyPlanningException(
                    "The planned target {$writer} is not in the project manifest.",
                    'unknown_target',
                );
            }
            $files = array_values(array_unique(array_map(
                fn (mixed $file): string => $this->paths->normalize((string) $file),
                is_array($node['files'] ?? null) ? $node['files'] : [$writer],
            )));
            if (!in_array($writer, $files, true)) {
                $files[] = $writer;
            }
            foreach ($files as $file) {
                if (!isset($known[$file]) && $file !== $writer) {
                    throw new EmpyPlanningException("Agent node {$nodeId} reads an unknown file {$file}.", 'unknown_context_file');
                }
            }
            $writers[$writer] = true;
            $node['writer'] = $writer;
            $node['files'] = $files;
            $node['action'] = $action;
            $validated[] = $node;
        }

        if (($validated ?? []) === []) {
            throw new EmpyPlanningException('The planner produced no executable agent.', 'empty_plan');
        }

        $plan['nodes'] = array_values($validated);
        $plan['writer_paths'] = array_keys($writers);
        return $plan;
    }
}
