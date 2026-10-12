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
            $contextMode = 'inline';
            try {
                $providerRequest = $this->requestFor($provider, $request);
                $contextMode = (string) ($providerRequest['context_mode'] ?? 'inline');
                $response = $provider->execute($providerRequest);
                $attempts[] = [
                    'provider' => $provider->id(),
                    'status' => 'succeeded',
                    'reason' => 'completed',
                    'context_mode' => $contextMode,
                ];

                return new ProviderRun($response, $provider->id(), $attempts, $contextMode);
            } catch (EmpyProviderException $exception) {
                $attempts[] = [
                    'provider' => $provider->id(),
                    'status' => 'failed',
                    'reason' => $exception->errorCode,
                    'message' => $exception->getMessage(),
                    'context_mode' => $contextMode,
                ];
                // A workspace hash mismatch means the context was built from
                // stale bytes. Falling back to an inline provider would send
                // that stale content and could overwrite a newer user edit.
                // Stop safely so the caller can rebuild the ticket context.
                if ($exception->errorCode === 'provider_workspace_stale') {
                    throw new EmpyProviderException($exception->getMessage(), $exception->errorCode, $attempts);
                }
            }
        }

        $code = $configured === [] ? 'provider_unavailable' : 'all_providers_failed';
        $message = $configured === []
            ? 'Provider آماده نیست: هیچ موتور مدلی فعال نیست. اتصال Codex، Gemini، Ollama یا یک endpoint سازگار را در تنظیمات فعال کنید.'
            : 'همهٔ Providerهای تنظیم‌شده شکست خوردند: '.$this->failureSummary($attempts);
        throw new EmpyProviderException($message, $code, $attempts);
    }

    /** @param array<string, mixed> $request @return array<string, mixed> */
    private function requestFor(ProviderAdapter $provider, array $request): array
    {
        $workspaceRead = $provider instanceof WorkspaceReadableProvider
            && $provider->supportsWorkspaceRead()
            && array_key_exists('workspace_allowlist', $request);
        $request['context_mode'] = $workspaceRead ? 'workspace-read' : 'inline';
        if ($workspaceRead) {
            $request['messages'] = $request['workspace_messages'] ?? $request['messages'] ?? [];
        } else {
            $request['messages'] = $request['inline_messages'] ?? $request['messages'] ?? [];
        }
        unset($request['inline_messages'], $request['workspace_messages']);

        return $request;
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
