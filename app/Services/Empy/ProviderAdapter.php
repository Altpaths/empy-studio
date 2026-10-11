<?php

namespace App\Services\Empy;

interface ProviderAdapter
{
    public function id(): string;

    public function configured(): bool;

    /** @param array<string, mixed> $request */
    public function execute(array $request): ProviderResponse;
}
