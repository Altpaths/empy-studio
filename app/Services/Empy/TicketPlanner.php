<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyPlanningException;
use App\Models\Ticket;
use Illuminate\Support\Str;

final class TicketPlanner
{
    public function __construct(private readonly AgentPlanValidator $validator)
    {
    }

    /** @return array<string, mixed> */
    public function plan(Ticket $ticket): array
    {
        $project = $ticket->project;
        $manifest = $project->manifest ?? [];
        $files = array_column($manifest['files'] ?? [], 'path');
        $text = trim($ticket->request_text);
        $lower = Str::lower($text);
        $explicit = $this->explicitPaths($text);
        $targets = [];
        foreach ($explicit as $candidate) {
            $matches = array_values(array_filter($files, static fn (string $path): bool => Str::lower($path) === Str::lower($candidate)));
            if ($matches !== []) {
                $targets[] = $matches[0];
            }
        }
        $creationRequest = $this->isCreationRequest($lower);
        if ($explicit !== [] && $targets === [] && !$creationRequest) {
            throw new EmpyPlanningException(
                'The requested file is not present in the project manifest.',
                'target_not_found',
            );
        }
        if ($explicit !== [] && $targets === [] && $creationRequest) {
            $targets = $explicit;
        }
        if ($targets === []) {
            $targets = $this->heuristicTargets($files, $manifest['entry_points'] ?? [], $lower);
        }
        if ($targets === []) {
            throw new EmpyPlanningException(
                'The project has no unambiguous writable entry point for this ticket.',
                'target_not_found',
            );
        }

        $action = $creationRequest ? 'create' : 'modify';
        $nodes = [];
        foreach (array_values(array_unique($targets)) as $index => $target) {
            $nodes[] = [
                'id' => 'agent-'.($index + 1),
                'role' => $this->roleFor($target, $lower),
                'writer' => $target,
                'files' => [$target],
                'action' => $action,
                'objective' => $text,
                'reason' => 'Selected from the project manifest and ticket target.',
            ];
        }
        $plan = [
            'version' => 1,
            'ticket_id' => $ticket->id,
            'objective' => $text,
            'nodes' => $nodes,
            'read_policy' => 'Only node files and their current hashes may enter context.',
            'recovery_policy' => 'Replan only after a changed graph fingerprint; never replay an identical failed graph.',
        ];
        $plan = $this->validator->validate($project, $plan);
        $plan['fingerprint'] = hash('sha256', json_encode($plan, JSON_THROW_ON_ERROR));

        $ticket->update([
            'plan' => $plan,
            'plan_fingerprint' => $plan['fingerprint'],
            'status' => 'planned',
            'failure_code' => null,
            'failure_detail' => null,
        ]);

        return $plan;
    }

    /** @return list<string> */
    private function explicitPaths(string $text): array
    {
        preg_match_all('/(?<![A-Za-z0-9_])([A-Za-z0-9_\.\/-]+\.(?:php|html?|css|scss|js|ts|vue|py|json|ya?ml|toml|md))(?![A-Za-z0-9_])/i', $text, $matches);
        return array_values(array_unique($matches[1] ?? []));
    }

    /** @param list<string> $files @param list<string> $entryPoints @return list<string> */
    private function heuristicTargets(array $files, array $entryPoints, string $text): array
    {
        $preferred = [];
        $api = str_contains($text, 'api') || str_contains($text, 'ای پی آی') || str_contains($text, 'رابط');
        $home = str_contains($text, 'home') || str_contains($text, 'homepage') || str_contains($text, 'صفحه اول') || str_contains($text, 'اولین صفحه');
        foreach ($files as $file) {
            $lower = Str::lower($file);
            if ($api && (str_contains($lower, 'routes/api') || str_contains($lower, 'routes/web') || str_contains($lower, 'controller'))) {
                $preferred[] = $file;
            }
            if ($home && (preg_match('#(^|/)public/index\.(php|html?)$#', $lower) || preg_match('#(^|/)index\.(php|html?)$#', $lower) || str_contains($lower, 'welcome.blade.php'))) {
                $preferred[] = $file;
            }
        }
        if ($preferred !== []) {
            return array_values(array_unique($preferred));
        }
        foreach ($entryPoints as $entry) {
            if (in_array($entry, $files, true)) {
                return [$entry];
            }
        }

        return [];
    }

    private function isCreationRequest(string $text): bool
    {
        foreach (['add', 'create', 'new', 'اضاف', 'ایجاد', 'ساخت'] as $word) {
            if (str_contains($text, $word)) {
                return true;
            }
        }

        return false;
    }

    private function roleFor(string $path, string $text): string
    {
        $lower = Str::lower($path);
        if (str_contains($text, 'api') || str_contains($text, 'ای پی آی') || str_contains($lower, 'routes/')) {
            return 'backend';
        }
        if (preg_match('/\.(html?|css|scss|js|ts|vue)$/', $lower) === 1) {
            return 'frontend';
        }

        return 'backend';
    }
}
