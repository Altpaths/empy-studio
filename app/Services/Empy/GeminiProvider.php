<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyProviderException;
use Illuminate\Support\Facades\Http;

/**
 * Optional Gemini REST fallback. It is never enabled without an explicit API
 * key and model, so provider failover cannot silently create a billable or
 * unauthorised account connection.
 */
final class GeminiProvider implements ProviderAdapter
{
    public function id(): string
    {
        return 'gemini';
    }

    public function configured(): bool
    {
        return trim((string) config('empy.gemini.api_key')) !== ''
            && trim((string) config('empy.gemini.model')) !== '';
    }

    public function execute(array $request): ProviderResponse
    {
        if (! $this->configured()) {
            throw new EmpyProviderException('Gemini provider is not configured.', 'provider_not_configured');
        }

        $messages = is_array($request['messages'] ?? null) ? $request['messages'] : [];
        $system = [];
        $contents = [];
        foreach ($messages as $message) {
            if (! is_array($message) || ! is_string($message['content'] ?? null)) {
                continue;
            }
            $role = (string) ($message['role'] ?? 'user');
            if ($role === 'system') {
                $system[] = $message['content'];

                continue;
            }
            $contents[] = [
                'role' => $role === 'assistant' ? 'model' : 'user',
                'parts' => [['text' => $message['content']]],
            ];
        }

        if ($contents === []) {
            throw new EmpyProviderException('Gemini request has no user content.', 'invalid_provider_request');
        }

        $payload = [
            'contents' => $contents,
            'generationConfig' => [
                'temperature' => 0.1,
                'responseMimeType' => 'application/json',
            ],
        ];
        if ($system !== []) {
            $payload['systemInstruction'] = ['parts' => [['text' => implode("\n\n", $system)]]];
        }

        $model = trim((string) config('empy.gemini.model'));
        $url = rtrim((string) config('empy.gemini.base_url'), '/').'/models/'.rawurlencode($model).':generateContent';
        try {
            $response = Http::timeout((int) config('empy.provider_timeout'))
                ->withHeaders(['x-goog-api-key' => (string) config('empy.gemini.api_key')])
                ->acceptJson()
                ->post($url, $payload);
        } catch (\Throwable) {
            throw new EmpyProviderException('Gemini provider could not be reached.', 'provider_transport');
        }

        if (! $response->successful()) {
            $status = $response->status();
            $code = in_array($status, [401, 403], true)
                ? 'provider_auth'
                : ($status === 429 ? 'provider_quota' : 'provider_http');
            throw new EmpyProviderException(
                $code === 'provider_quota'
                    ? 'Gemini quota or rate limit was reached; trying the next configured provider.'
                    : 'Gemini provider returned HTTP '.$status.'.',
                $code,
            );
        }

        $json = $response->json();
        $content = data_get($json, 'candidates.0.content.parts.0.text');
        if (! is_string($content)) {
            throw new EmpyProviderException('Gemini returned no structured message content.', 'invalid_provider_output');
        }
        $payload = json_decode($this->stripFence($content), true);
        if (! is_array($payload)) {
            throw new EmpyProviderException('Gemini did not return valid JSON.', 'invalid_provider_output');
        }

        $usage = (array) data_get($json, 'usageMetadata', []);

        return ProviderResponse::fromPayload($payload + ['usage' => [
            'prompt_tokens' => $usage['promptTokenCount'] ?? null,
            'completion_tokens' => $usage['candidatesTokenCount'] ?? null,
            'total_tokens' => $usage['totalTokenCount'] ?? null,
        ]]);
    }

    private function stripFence(string $content): string
    {
        return trim((string) preg_replace('/^```(?:json)?\s*|\s*```$/i', '', trim($content)));
    }
}
