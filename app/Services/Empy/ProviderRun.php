<?php

namespace App\Services\Empy;

final readonly class ProviderRun
{
    /** @param list<array<string, mixed>> $attempts */
    public function __construct(
        public ProviderResponse $response,
        public string $provider,
        public array $attempts,
    ) {}
}
