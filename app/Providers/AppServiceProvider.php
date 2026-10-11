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
        $this->app->singleton(ProviderManager::class, static function (): ProviderManager {
            $adapters = [
                'ollama' => new OllamaProvider(),
                'openai_compatible' => new OpenAiCompatibleProvider(),
            ];
            $ordered = [];
            foreach ((array) config('empy.provider_order', []) as $provider) {
                if (isset($adapters[$provider])) {
                    $ordered[] = $adapters[$provider];
                }
            }

            return new ProviderManager($ordered);
        });
    }

    public function boot(): void
    {
    }
}
