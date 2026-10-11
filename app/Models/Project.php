<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Project extends Model
{
    use HasUuids;

    protected $fillable = [
        'name', 'original_filename', 'source_disk', 'source_path', 'status',
        'manifest', 'detected_stack',
    ];

    protected function casts(): array
    {
        return ['manifest' => 'array', 'detected_stack' => 'array'];
    }

    public function tickets(): HasMany
    {
        return $this->hasMany(Ticket::class);
    }
}
