<?php

namespace App\Exceptions;

use RuntimeException;

class EmpyVerificationException extends RuntimeException
{
    public function __construct(
        string $message,
        public readonly string $errorCode = 'verification_failed',
    ) {
        parent::__construct($message);
    }
}
