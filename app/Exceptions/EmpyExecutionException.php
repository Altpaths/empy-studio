<?php

namespace App\Exceptions;

use RuntimeException;

class EmpyExecutionException extends RuntimeException
{
    public function __construct(
        string $message,
        public readonly string $errorCode = 'execution_failed',
    ) {
        parent::__construct($message);
    }
}
