<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('run_events', function (Blueprint $table): void {
            $table->id();
            $table->foreignUuid('run_id')->constrained()->cascadeOnDelete();
            $table->string('kind');
            $table->text('message');
            $table->json('payload')->nullable();
            $table->timestamps();
            $table->index(['run_id', 'created_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('run_events');
    }
};
