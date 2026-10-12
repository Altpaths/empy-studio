<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Ticket extends Model
{
    use HasUuids;

    protected $fillable = [
        'project_id', 'title', 'request_text', 'status', 'plan',
        'plan_fingerprint', 'baseline_manifest', 'result', 'failure_code', 'failure_detail',
        'attempts', 'started_at', 'finished_at',
    ];

    protected function casts(): array
    {
        return [
            'plan' => 'array', 'baseline_manifest' => 'array', 'result' => 'array', 'started_at' => 'datetime',
            'finished_at' => 'datetime',
        ];
    }

    public function project(): BelongsTo
    {
        return $this->belongsTo(Project::class);
    }

    public function runs(): HasMany
    {
        return $this->hasMany(Run::class);
    }

    public function artifacts(): HasMany
    {
        return $this->hasMany(Artifact::class);
    }
}
