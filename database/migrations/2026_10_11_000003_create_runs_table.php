<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('runs', function (Blueprint $table): void {
            $table->uuid('id')->primary();
            $table->foreignUuid('ticket_id')->constrained()->cascadeOnDelete();
            $table->unsignedInteger('attempt');
            $table->string('status')->default('queued');
            $table->string('provider')->nullable();
            $table->string('graph_fingerprint')->nullable()->index();
            $table->json('context_stats')->nullable();
            $table->string('failure_code')->nullable();
            $table->text('failure_detail')->nullable();
            $table->timestamp('started_at')->nullable();
            $table->timestamp('finished_at')->nullable();
            $table->timestamps();
            $table->unique(['ticket_id', 'attempt']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('runs');
    }
};
