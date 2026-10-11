<?php

namespace App\Services\Empy;

use App\Models\Run;
use App\Models\Ticket;

final class RecoveryService
{
    public function __construct(private readonly RecoveryPolicy $policy) {}

    public function prepareNextAttempt(Ticket $ticket, Run $run): bool
    {
        $decision = $this->policy->decide($ticket, $run);
        if (! $decision['retry']) {
            $ticket->update([
                'failure_detail' => trim(($ticket->failure_detail ?? '').' Recovery متوقف شد: '.$decision['reason'].'.'),
            ]);

            return false;
        }
        $plan = $ticket->plan ?? [];
        $count = ((int) ($plan['recovery_count'] ?? 0)) + 1;
        $plan['recovery_count'] = $count;
        $plan['recovery_hint'] = match ($run->failure_code) {
            'no_project_change' => 'Produce a materially different patch for the assigned writer; do not return the current content unchanged.',
            'out_of_scope_write' => 'Return exactly one file whose path equals the assigned writer.',
            'invalid_provider_output', 'empty_provider_output' => 'Return strict JSON with one complete file patch and no prose outside JSON.',
            default => 'Use a different implementation strategy and show a real file diff.',
        };
        $plan['fingerprint'] = hash('sha256', json_encode($plan, JSON_THROW_ON_ERROR));
        $ticket->update([
            'status' => 'planned',
            'plan' => $plan,
            'plan_fingerprint' => $plan['fingerprint'],
            'failure_code' => null,
            'failure_detail' => null,
        ]);
        $run->events()->create([
            'kind' => 'recovery_replanned',
            'message' => 'A changed recovery graph was prepared; the identical failed graph will not be replayed.',
            'payload' => ['recovery_count' => $count, 'new_fingerprint' => $plan['fingerprint']],
        ]);

        return true;
    }
}
