<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('context_entries', function (Blueprint $table): void {
            $table->id();
            $table->foreignUuid('project_id')->constrained()->cascadeOnDelete();
            $table->string('path');
            $table->string('source_sha256', 64);
            $table->text('summary')->nullable();
            $table->unsignedInteger('summary_tokens')->default(0);
            $table->timestamps();
            $table->unique(['project_id', 'path']);
            $table->index(['project_id', 'source_sha256']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('context_entries');
    }
};
