<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class Artifact extends Model
{
    use HasUuids;

    protected $fillable = [
        'ticket_id', 'disk', 'path', 'sha256', 'size', 'manifest',
    ];

    protected function casts(): array
    {
        return ['manifest' => 'array'];
    }

    public function ticket(): BelongsTo
    {
        return $this->belongsTo(Ticket::class);
    }
}
