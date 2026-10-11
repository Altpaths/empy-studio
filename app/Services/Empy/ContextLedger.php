<?php

namespace App\Services\Empy;

use App\Models\Project;
use App\Support\Empy\PathGuard;
use Illuminate\Support\Facades\Storage;
use RuntimeException;

final class ContextLedger
{
    public function __construct(private readonly PathGuard $paths) {}

    /**
     * Build the aggregate ledger and a separate context slice for each agent.
     * The aggregate is kept for reporting, while execution uses node-specific
     * slices so the same files are not sent to every provider.
     *
     * @param  array<string, mixed>  $plan
     * @return array{items: list<array<string, mixed>>, items_by_node: array<string, list<array<string, mixed>>>, stats: array<string, mixed>}
     */
    public function build(Project $project, array $plan): array
    {
        $root = Storage::disk($project->source_disk)->path($project->source_path);
        $manifest = array_fill_keys(array_column($project->manifest['files'] ?? [], 'path'), true);
        $itemsByNode = [];
        $allItems = [];
        $totalNodeFiles = 0;
        $totalNodeTokens = 0;

        foreach ($plan['nodes'] ?? [] as $node) {
            $nodeId = (string) ($node['id'] ?? 'unknown');
            $nodeItems = $this->buildNode($root, $manifest, $node);
            $itemsByNode[$nodeId] = $nodeItems;
            $totalNodeFiles += count($nodeItems);
            $totalNodeTokens += array_sum(array_map(
                static fn (array $item): int => (int) $item['estimated_tokens'],
                $nodeItems,
            ));
            foreach ($nodeItems as $item) {
                $allItems[$item['path']] ??= $item;
            }
        }

        $items = array_values($allItems);
        $uniqueChars = array_sum(array_map(
            static fn (array $item): int => (int) $item['chars'],
            $items,
        ));
        $uniqueTokens = array_sum(array_map(
            static fn (array $item): int => (int) $item['estimated_tokens'],
            $items,
        ));
        $nodeStats = [];
        foreach ($itemsByNode as $nodeId => $nodeItems) {
            $nodeStats[$nodeId] = [
                'files' => count($nodeItems),
                'chars' => array_sum(array_map(
                    static fn (array $item): int => (int) $item['chars'],
                    $nodeItems,
                )),
                'estimated_tokens' => array_sum(array_map(
                    static fn (array $item): int => (int) $item['estimated_tokens'],
                    $nodeItems,
                )),
            ];
        }
        $nodeCount = count($itemsByNode);
        $naivePromptTokens = $nodeCount * $uniqueTokens;

        return [
            'items' => $items,
            'items_by_node' => $itemsByNode,
            'stats' => [
                'files' => count($items),
                'unique_files' => count($items),
                'chars' => $uniqueChars,
                'estimated_tokens' => $uniqueTokens,
                'reused_files' => max(0, $totalNodeFiles - count($items)),
                'nodes' => $nodeCount,
                'total_node_tokens' => $totalNodeTokens,
                'naive_prompt_tokens' => $naivePromptTokens,
                'saved_prompt_tokens' => max(0, $naivePromptTokens - $totalNodeTokens),
                'node_stats' => $nodeStats,
            ],
        ];
    }

    /**
     * @param  array<string, bool>  $manifest
     * @param  array<string, mixed>  $node
     * @return list<array<string, mixed>>
     */
    private function buildNode(string $root, array $manifest, array $node): array
    {
        $writer = $this->paths->normalize((string) ($node['writer'] ?? ''));
        $paths = [];
        foreach (($node['files'] ?? []) as $path) {
            $path = $this->paths->normalize((string) $path);
            if (! isset($manifest[$path])) {
                if (($node['action'] ?? 'modify') === 'create' && $path === $writer) {
                    continue;
                }
                throw new RuntimeException("Context path {$path} is not in the project manifest.");
            }
            $paths[$path] = true;
        }

        $items = [];
        foreach (array_keys($paths) as $path) {
            $absolute = $this->paths->join($root, $path);
            if (! is_file($absolute) || is_link($absolute)) {
                throw new RuntimeException("Context file {$path} is not readable.");
            }
            $content = file_get_contents($absolute);
            if ($content === false) {
                throw new RuntimeException("Context file {$path} could not be read.");
            }
            $chars = strlen($content);
            $items[] = [
                'path' => $path,
                'sha256' => hash('sha256', $content),
                'content' => $content,
                'chars' => $chars,
                'estimated_tokens' => (int) ceil($chars / 4),
            ];
        }

        return $items;
    }
}
