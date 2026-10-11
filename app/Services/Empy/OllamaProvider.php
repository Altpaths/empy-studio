<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyProviderException;
use Illuminate\Support\Facades\Http;

final class OllamaProvider implements ProviderAdapter
{
    public function id(): string
    {
        return 'ollama';
    }

    public function configured(): bool
    {
        return trim((string) config('empy.ollama.model')) !== '';
    }

    public function execute(array $request): ProviderResponse
    {
        $model = trim((string) config('empy.ollama.model'));
        if (! $this->configured()) {
            throw new EmpyProviderException('Ollama model is not configured.', 'provider_not_configured');
        }

        try {
            $response = Http::timeout((int) config('empy.provider_timeout'))
                ->acceptJson()
                ->post(rtrim((string) config('empy.ollama.base_url'), '/').'/api/chat', [
                    'model' => $model,
                    'stream' => false,
                    'format' => 'json',
                    'messages' => $request['messages'] ?? [],
                    'options' => ['temperature' => 0.1],
                ]);
        } catch (\Throwable) {
            throw new EmpyProviderException('Ollama could not be reached.', 'provider_transport');
        }
        if (! $response->successful()) {
            $status = $response->status();
            throw new EmpyProviderException(
                $status === 429
                    ? 'Ollama rate limit was reached; trying the next configured provider.'
                    : 'Ollama returned HTTP '.$status.'.',
                $status === 429 ? 'provider_quota' : 'provider_http',
            );
        }

        $content = data_get($response->json(), 'message.content');
        if (! is_string($content)) {
            throw new EmpyProviderException('Ollama returned no message content.', 'invalid_provider_output');
        }
        $payload = json_decode($this->stripFence($content), true);
        if (! is_array($payload)) {
            throw new EmpyProviderException('Ollama did not return valid JSON.', 'invalid_provider_output');
        }

        return ProviderResponse::fromPayload($payload + ['usage' => [
            'prompt_tokens' => data_get($response->json(), 'prompt_eval_count'),
            'completion_tokens' => data_get($response->json(), 'eval_count'),
        ]]);
    }

    private function stripFence(string $content): string
    {
        return trim((string) preg_replace('/^```(?:json)?\s*|\s*```$/i', '', trim($content)));
    }
}
