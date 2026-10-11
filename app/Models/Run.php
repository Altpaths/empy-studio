<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Run extends Model
{
    use HasUuids;

    protected $fillable = [
        'ticket_id', 'attempt', 'status', 'provider', 'graph_fingerprint',
        'context_stats', 'failure_code', 'failure_detail', 'started_at',
        'finished_at',
    ];

    protected function casts(): array
    {
        return [
            'context_stats' => 'array', 'started_at' => 'datetime',
            'finished_at' => 'datetime',
        ];
    }

    public function ticket(): BelongsTo
    {
        return $this->belongsTo(Ticket::class);
    }

    public function events(): HasMany
    {
        return $this->hasMany(RunEvent::class);
    }
}
