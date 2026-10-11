<?php

namespace App\Providers;

use App\Services\Empy\OllamaProvider;
use App\Services\Empy\OpenAiCompatibleProvider;
use App\Services\Empy\ProviderManager;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->app->singleton(ProviderManager::class, static fn (): ProviderManager => new ProviderManager([
            new OllamaProvider(),
            new OpenAiCompatibleProvider(),
        ]));
    }

    public function boot(): void
    {
    }
}
