<?php

namespace App\Exceptions;

use RuntimeException;

class EmpyProviderException extends RuntimeException
{
    /** @param list<array<string, mixed>> $attempts */
    public function __construct(
        string $message,
        public readonly string $errorCode = 'provider_failed',
        public readonly array $attempts = [],
    ) {
        parent::__construct($message);
    }
}
