<?php

namespace Tests\Feature\Empy;

use App\Exceptions\EmpyProviderException;
use App\Services\Empy\OllamaProvider;
use App\Services\Empy\OpenAiCompatibleProvider;
use App\Services\Empy\ProviderManager;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class ProviderAdapterTest extends TestCase
{
    use RefreshDatabase;

    public function test_ollama_adapter_parses_structured_json_and_usage(): void
    {
        config()->set('empy.ollama.model', 'local-test');
        Http::fake([
            'http://ollama.test/api/chat' => Http::response([
                'message' => ['content' => json_encode([
                    'summary' => 'changed',
                    'files' => [['path' => 'index.html', 'content' => '<main>new</main>']],
                ])],
                'prompt_eval_count' => 12,
                'eval_count' => 7,
            ], 200),
        ]);
        config()->set('empy.ollama.base_url', 'http://ollama.test');

        $run = (new ProviderManager([new OllamaProvider()]))->execute(['messages' => []]);

        $this->assertSame('ollama', $run->provider);
        $this->assertSame('index.html', $run->response->files[0]['path']);
        $this->assertSame(12, $run->response->usage['prompt_tokens']);
    }

    public function test_manager_records_failed_provider_then_uses_the_next_configured_adapter(): void
    {
        config()->set('empy.openai_compatible.base_url', 'http://gateway.test/v1');
        config()->set('empy.openai_compatible.model', 'gateway-test');
        config()->set('empy.ollama.model', 'local-test');
        config()->set('empy.ollama.base_url', 'http://ollama.test');
        Http::fake([
            'http://gateway.test/v1/chat/completions' => Http::response([], 503),
            'http://ollama.test/api/chat' => Http::response([
                'message' => ['content' => '{"summary":"local","files":[{"path":"index.html","content":"ok"}]}'],
            ], 200),
        ]);

        $run = (new ProviderManager([new OpenAiCompatibleProvider(), new OllamaProvider()]))->execute(['messages' => []]);

        $this->assertSame('ollama', $run->provider);
        $this->assertSame('failed', $run->attempts[0]['status']);
        $this->assertSame('succeeded', $run->attempts[1]['status']);
    }

    public function test_manager_exposes_provider_unavailable_without_making_a_model_call(): void
    {
        Http::fake();
        try {
            (new ProviderManager([new OllamaProvider(), new OpenAiCompatibleProvider()]))->execute(['messages' => []]);
            $this->fail('Expected provider_unavailable.');
        } catch (EmpyProviderException $exception) {
            $this->assertSame('provider_unavailable', $exception->errorCode);
            $this->assertCount(2, $exception->attempts);
            Http::assertNothingSent();
        }
    }
}
