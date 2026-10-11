<?php

namespace App\Services\Empy;

use App\Models\Run;
use App\Models\Ticket;

final class RecoveryPolicy
{
    /** @return array{retry: bool, reason: string} */
    public function decide(Ticket $ticket, Run $run): array
    {
        $recoveryCount = (int) ($ticket->plan['recovery_count'] ?? 0);
        if ($recoveryCount >= 3) {
            return ['retry' => false, 'reason' => 'recovery_budget_exhausted_after_changed_strategies'];
        }
        $sameGraphFailures = $ticket->runs()
            ->where('id', '!=', $run->id)
            ->where('graph_fingerprint', $run->graph_fingerprint)
            ->where('failure_code', $run->failure_code)
            ->exists();
        if ($sameGraphFailures) {
            return ['retry' => false, 'reason' => 'same_graph_same_failure'];
        }
        if (in_array($run->failure_code, ['provider_unavailable', 'all_providers_failed', 'plan_required', 'unknown_target', 'duplicate_writer'], true)) {
            return ['retry' => false, 'reason' => 'requires_configuration_or_plan_change'];
        }

        return ['retry' => true, 'reason' => 'a different strategy may make progress'];
    }
}
