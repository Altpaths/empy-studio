<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyProviderException;
use Illuminate\Support\Facades\Http;

final class OpenAiCompatibleProvider implements ProviderAdapter
{
    public function id(): string
    {
        return 'openai_compatible';
    }

    public function configured(): bool
    {
        return trim((string) config('empy.openai_compatible.base_url')) !== ''
            && trim((string) config('empy.openai_compatible.model')) !== '';
    }

    public function execute(array $request): ProviderResponse
    {
        if (! $this->configured()) {
            throw new EmpyProviderException('OpenAI-compatible provider is not configured.', 'provider_not_configured');
        }
        $headers = [];
        $key = trim((string) config('empy.openai_compatible.api_key'));
        if ($key !== '') {
            $headers['Authorization'] = 'Bearer '.$key;
        }

        try {
            $response = Http::timeout((int) config('empy.provider_timeout'))
                ->withHeaders($headers)
                ->acceptJson()
                ->post(rtrim((string) config('empy.openai_compatible.base_url'), '/').'/chat/completions', [
                    'model' => (string) config('empy.openai_compatible.model'),
                    'temperature' => 0.1,
                    'response_format' => ['type' => 'json_object'],
                    'messages' => $request['messages'] ?? [],
                ]);
        } catch (\Throwable) {
            throw new EmpyProviderException('OpenAI-compatible provider could not be reached.', 'provider_transport');
        }
        if (! $response->successful()) {
            throw new EmpyProviderException('OpenAI-compatible provider returned HTTP '.$response->status().'.', 'provider_http');
        }
        $content = data_get($response->json(), 'choices.0.message.content');
        if (! is_string($content)) {
            throw new EmpyProviderException('Provider returned no message content.', 'invalid_provider_output');
        }
        $payload = json_decode(trim($content), true);
        if (! is_array($payload)) {
            throw new EmpyProviderException('Provider did not return valid JSON.', 'invalid_provider_output');
        }

        return ProviderResponse::fromPayload($payload + ['usage' => (array) data_get($response->json(), 'usage')]);
    }
}
