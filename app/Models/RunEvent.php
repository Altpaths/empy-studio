<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class RunEvent extends Model
{
    protected $fillable = ['run_id', 'kind', 'message', 'payload'];

    protected function casts(): array
    {
        return ['payload' => 'array'];
    }

    public function run(): BelongsTo
    {
        return $this->belongsTo(Run::class);
    }
}
