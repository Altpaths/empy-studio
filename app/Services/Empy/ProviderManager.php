<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyProviderException;

final class ProviderManager
{
    /** @param list<ProviderAdapter> $providers */
    public function __construct(private readonly array $providers) {}

    /** @param array<string, mixed> $request */
    public function execute(array $request): ProviderRun
    {
        $attempts = [];
        $configured = [];
        foreach ($this->providers as $provider) {
            if (! $provider->configured()) {
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
            ? 'Provider آماده نیست: هیچ موتور مدلی فعال نیست. اتصال Codex، Gemini، Ollama یا یک endpoint سازگار را در تنظیمات فعال کنید.'
            : 'همهٔ Providerهای تنظیم‌شده شکست خوردند: '.$this->failureSummary($attempts);
        throw new EmpyProviderException($message, $code, $attempts);
    }

    /** @param list<array<string, mixed>> $attempts */
    private function failureSummary(array $attempts): string
    {
        $failures = array_values(array_filter($attempts, static fn (array $attempt): bool => ($attempt['status'] ?? null) === 'failed'));
        if ($failures === []) {
            return 'هیچ تلاش قابل اجرایی ثبت نشد.';
        }

        return implode('؛ ', array_map(
            static fn (array $attempt): string => (string) ($attempt['provider'] ?? 'unknown').' → '.(string) ($attempt['reason'] ?? 'unknown'),
            $failures,
        )).'.';
    }

    /** @return list<string> */
    public function configuredIds(): array
    {
        return array_values(array_map(
            static fn (ProviderAdapter $provider): string => $provider->id(),
            array_filter($this->providers, static fn (ProviderAdapter $provider): bool => $provider->configured()),
        ));
    }
}
