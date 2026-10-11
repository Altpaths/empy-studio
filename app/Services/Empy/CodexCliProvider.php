<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyProviderException;

/**
 * Uses a locally authenticated Codex CLI session as an explicit provider.
 *
 * The CLI runs in read-only mode and returns a structured patch. Empy remains
 * the only writer: the returned files still pass through PatchApplier and the
 * normal verification/delivery gates.
 */
final class CodexCliProvider implements ProviderAdapter
{
    public function id(): string
    {
        return 'codex';
    }

    public function configured(): bool
    {
        return (bool) config('empy.codex.enabled', true) && $this->binary() !== null;
    }

    public function execute(array $request): ProviderResponse
    {
        $binary = $this->binary();
        $workspace = is_string($request['workspace_path'] ?? null) ? $request['workspace_path'] : '';

        if ($binary === null) {
            throw new EmpyProviderException('Codex CLI is not installed or is not executable.', 'provider_not_configured');
        }
        if ($workspace === '' || ! is_dir($workspace)) {
            throw new EmpyProviderException('Codex provider received an invalid project workspace.', 'provider_workspace');
        }

        $directory = storage_path('framework/cache/empy-codex');
        if (! is_dir($directory) && ! @mkdir($directory, 0700, true) && ! is_dir($directory)) {
            throw new EmpyProviderException('Codex provider could not create its temporary workspace.', 'provider_storage');
        }

        $runDirectory = $directory.'/'.bin2hex(random_bytes(12));
        if (! @mkdir($runDirectory, 0700) && ! is_dir($runDirectory)) {
            throw new EmpyProviderException('Codex provider could not allocate a temporary run.', 'provider_storage');
        }

        $promptPath = $runDirectory.'/prompt.txt';
        $schemaPath = $runDirectory.'/schema.json';
        $outputPath = $runDirectory.'/output.json';
        $stderrPath = $runDirectory.'/stderr.log';
        $stdoutPath = $runDirectory.'/stdout.log';
        $schema = $this->schema();

        file_put_contents($promptPath, $this->prompt($request['messages'] ?? []));
        file_put_contents($schemaPath, json_encode($schema, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));

        $command = [
            $binary,
            'exec',
            '--ephemeral',
            '--ignore-user-config',
            '--ignore-rules',
            '--json',
            '--sandbox',
            'read-only',
            '--skip-git-repo-check',
            '--cd',
            $workspace,
            '--output-schema',
            $schemaPath,
            '--output-last-message',
            $outputPath,
        ];
        $model = trim((string) config('empy.codex.model'));
        if ($model !== '') {
            $command[] = '--model';
            $command[] = $model;
        }

        $commandLine = implode(' ', array_map(static fn (string $part): string => escapeshellarg($part), $command));
        $descriptors = [
            0 => ['file', $promptPath, 'r'],
            1 => ['file', $stdoutPath, 'w'],
            2 => ['file', $stderrPath, 'w'],
        ];
        $process = @proc_open($commandLine, $descriptors, $pipes, $workspace);
        if (! is_resource($process)) {
            $this->cleanup($runDirectory);
            throw new EmpyProviderException('Codex CLI could not be started.', 'provider_transport');
        }

        $timeout = max(10, (int) config('empy.codex.timeout', config('empy.provider_timeout', 300)));
        $started = microtime(true);
        $exitCode = null;
        do {
            $status = proc_get_status($process);
            $exitCode = $status['exitcode'] ?? null;
            if (! $status['running']) {
                break;
            }
            usleep(100_000);
        } while (microtime(true) - $started < $timeout);

        if ($exitCode === null && microtime(true) - $started >= $timeout) {
            @proc_terminate($process, 15);
            usleep(200_000);
            @proc_terminate($process, 9);
            proc_close($process);
            $this->cleanup($runDirectory);
            throw new EmpyProviderException('Codex provider timed out before returning a patch.', 'provider_timeout');
        }

        $closeCode = proc_close($process);
        $exitCode = is_int($exitCode) && $exitCode >= 0 ? $exitCode : $closeCode;
        $content = is_file($outputPath) ? trim((string) file_get_contents($outputPath)) : '';
        $stdout = is_file($stdoutPath) ? (string) file_get_contents($stdoutPath) : '';
        $stderr = is_file($stderrPath) ? strtolower((string) file_get_contents($stderrPath)) : '';
        $usage = $this->usage($stdout);
        $this->cleanup($runDirectory);

        if ($exitCode !== 0 && $content === '') {
            $code = str_contains($stderr, 'log in') || str_contains($stderr, 'authentication')
                ? 'provider_auth'
                : (preg_match('/\b(quota|rate limit|rate-limit|context window|token limit|tokens remaining)\b/i', $stderr) === 1
                    ? 'provider_quota'
                    : 'provider_execution');
            throw new EmpyProviderException(
                match ($code) {
                    'provider_auth' => 'Codex is not signed in. Connect the ChatGPT account once, then retry.',
                    'provider_quota' => 'Codex quota or context limit was reached; trying the next configured provider.',
                    default => 'Codex stopped before returning a structured patch.',
                },
                $code,
            );
        }

        $payload = $this->decodePayload($content);
        if (! is_array($payload)) {
            throw new EmpyProviderException('Codex returned an invalid structured patch.', 'invalid_provider_output');
        }

        return ProviderResponse::fromPayload($payload + ['usage' => $usage]);
    }

    /** @return array<string, mixed> */
    private function schema(): array
    {
        return [
            'type' => 'object',
            'additionalProperties' => false,
            // Codex's strict structured-output mode requires every declared
            // property to appear in `required`; optional values are represented
            // as an empty string instead of being omitted.
            'required' => ['summary', 'context_summary', 'files'],
            'properties' => [
                'summary' => ['type' => 'string'],
                'context_summary' => ['type' => 'string'],
                'files' => [
                    'type' => 'array',
                    'minItems' => 1,
                    'items' => [
                        'type' => 'object',
                        'additionalProperties' => false,
                        'required' => ['path', 'content'],
                        'properties' => [
                            'path' => ['type' => 'string'],
                            'content' => ['type' => 'string'],
                        ],
                    ],
                ],
            ],
        ];
    }

    /** @param list<array<string, mixed>> $messages */
    private function prompt(array $messages): string
    {
        $parts = [];
        foreach ($messages as $message) {
            if (! is_array($message) || ! is_string($message['content'] ?? null)) {
                continue;
            }
            $role = is_string($message['role'] ?? null) ? strtoupper($message['role']) : 'MESSAGE';
            $parts[] = "[$role]\n{$message['content']}";
        }

        return implode("\n\n---\n\n", $parts)."\n\nProvider contract: use only the context above. Do not perform discovery, do not modify files, do not run commands, and return only the requested structured JSON patch. The assigned writer paths are the only paths that may appear in files. Include complete file contents and set context_summary to an empty string when there is nothing to add.\n";
    }

    /** @return array<string, int|float|null> */
    private function usage(string $stdout): array
    {
        $usage = [];
        foreach (preg_split('/\R/', $stdout) ?: [] as $line) {
            $event = json_decode(trim($line), true);
            if (! is_array($event) || ($event['type'] ?? null) !== 'turn.completed') {
                continue;
            }
            if (is_array($event['usage'] ?? null)) {
                $usage = $event['usage'];
            }
        }

        return $usage;
    }

    /** @return array<string, mixed>|null */
    private function decodePayload(string $content): ?array
    {
        $content = trim((string) preg_replace('/^```(?:json)?\s*|\s*```$/i', '', $content));
        $payload = json_decode($content, true);
        if (is_array($payload)) {
            return $payload;
        }

        return null;
    }

    private function binary(): ?string
    {
        $configured = trim((string) config('empy.codex.binary', 'codex'));
        $candidates = [$configured];
        if ($configured === 'codex') {
            $candidates = array_merge($candidates, [
                base_path('desktop/runtime/codex'),
                '/opt/homebrew/bin/codex',
                '/usr/local/bin/codex',
            ]);
        }

        foreach (array_unique($candidates) as $candidate) {
            if (is_file($candidate) && is_executable($candidate)) {
                return $candidate;
            }
        }

        return null;
    }

    private function cleanup(string $directory): void
    {
        foreach (glob($directory.'/*') ?: [] as $path) {
            if (is_file($path)) {
                @unlink($path);
            }
        }
        @rmdir($directory);
    }
}
