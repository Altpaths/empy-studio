<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyProviderException;

final class ProviderManager
{
    /** @param list<ProviderAdapter> $providers */
    public function __construct(private readonly array $providers)
    {
    }

    /** @param array<string, mixed> $request */
    public function execute(array $request): ProviderRun
    {
        $attempts = [];
        $configured = [];
        foreach ($this->providers as $provider) {
            if (!$provider->configured()) {
                $attempts[] = ['provider' => $provider->id(), 'status' => 'skipped', 'reason' => 'not_configured'];
                continue;
            }
            $configured[] = $provider;
            try {
                $response = $provider->execute($request);
                $attempts[] = ['provider' => $provider->id(), 'status' => 'succeeded', 'reason' => 'completed'];
                return new ProviderRun($response, $provider->id(), $attempts);
            } catch (EmpyProviderException $exception) {
                $attempts[] = [
                    'provider' => $provider->id(),
                    'status' => 'failed',
                    'reason' => $exception->errorCode,
                    'message' => $exception->getMessage(),
                ];
            }
        }

        $code = $configured === [] ? 'provider_unavailable' : 'all_providers_failed';
        $message = $configured === []
            ? 'هیچ Provider فعالی تنظیم نشده است. Ollama یا یک endpoint سازگار را تنظیم کنید.'
            : 'همهٔ Providerهای تنظیم‌شده شکست خوردند؛ جزئیات تلاش‌ها ثبت شده است.';
        throw new EmpyProviderException($message, $code, $attempts);
    }
}
