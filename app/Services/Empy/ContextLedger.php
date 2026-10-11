<?php

namespace App\Services\Empy;

use App\Models\Project;
use App\Support\Empy\PathGuard;
use Illuminate\Support\Facades\Storage;
use RuntimeException;

final class ContextLedger
{
    public function __construct(private readonly PathGuard $paths)
    {
    }

    /** @param array<string, mixed> $plan @return array{items: list<array<string, mixed>>, stats: array<string, int>} */
    public function build(Project $project, array $plan): array
    {
        $root = Storage::disk($project->source_disk)->path($project->source_path);
        $manifest = array_fill_keys(array_column($project->manifest['files'] ?? [], 'path'), true);
        $paths = [];
        foreach ($plan['nodes'] ?? [] as $node) {
            foreach (($node['files'] ?? []) as $path) {
                $path = $this->paths->normalize((string) $path);
                if (!isset($manifest[$path])) {
                    throw new RuntimeException("Context path {$path} is not in the project manifest.");
                }
                $paths[$path] = true;
            }
        }

        $items = [];
        $totalChars = 0;
        foreach (array_keys($paths) as $path) {
            $absolute = $this->paths->join($root, $path);
            if (!is_file($absolute) || is_link($absolute)) {
                throw new RuntimeException("Context file {$path} is not readable.");
            }
            $content = file_get_contents($absolute);
            if ($content === false) {
                throw new RuntimeException("Context file {$path} could not be read.");
            }
            $sha = hash('sha256', $content);
            $chars = strlen($content);
            $totalChars += $chars;
            $items[] = [
                'path' => $path,
                'sha256' => $sha,
                'content' => $content,
                'chars' => $chars,
                'estimated_tokens' => (int) ceil($chars / 4),
            ];
        }

        return [
            'items' => $items,
            'stats' => [
                'files' => count($items),
                'unique_files' => count($items),
                'chars' => $totalChars,
                'estimated_tokens' => (int) ceil($totalChars / 4),
                'reused_files' => 0,
            ],
        ];
    }
}
