<?php

namespace App\Exceptions;

use RuntimeException;

class EmpyPlanningException extends RuntimeException
{
    public function __construct(
        string $message,
        public readonly string $errorCode = 'planning_failed',
    ) {
        parent::__construct($message);
    }
}
