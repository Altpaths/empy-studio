<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class ContextEntry extends Model
{
    protected $fillable = [
        'project_id', 'path', 'source_sha256', 'summary', 'summary_tokens',
    ];

    public function project(): BelongsTo
    {
        return $this->belongsTo(Project::class);
    }
}
