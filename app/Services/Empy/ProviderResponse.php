<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyProviderException;

final readonly class ProviderResponse
{
    /** @param list<array{path: string, content: string}> $files */
    public function __construct(
        public array $files,
        public string $summary,
        public array $usage = [],
        public ?string $contextSummary = null,
    ) {}

    /** @param array<string, mixed> $payload */
    public static function fromPayload(array $payload): self
    {
        $files = [];
        foreach (($payload['files'] ?? []) as $file) {
            if (! is_array($file) || ! is_string($file['path'] ?? null) || ! is_string($file['content'] ?? null)) {
                throw new EmpyProviderException('Provider returned an invalid file patch.', 'invalid_provider_output');
            }
            $files[] = ['path' => $file['path'], 'content' => $file['content']];
        }
        if ($files === []) {
            throw new EmpyProviderException('Provider returned no file patch.', 'empty_provider_output');
        }

        return new self(
            files: $files,
            summary: is_string($payload['summary'] ?? null) ? $payload['summary'] : 'Provider produced a structured patch.',
            usage: is_array($payload['usage'] ?? null) ? $payload['usage'] : [],
            contextSummary: is_string($payload['context_summary'] ?? null) ? $payload['context_summary'] : null,
        );
    }
}
