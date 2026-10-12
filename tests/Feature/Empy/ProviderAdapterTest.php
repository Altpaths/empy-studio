<?php

namespace Tests\Feature\Empy;

use App\Exceptions\EmpyProviderException;
use App\Services\Empy\CodexCliProvider;
use App\Services\Empy\GeminiProvider;
use App\Services\Empy\OllamaProvider;
use App\Services\Empy\OpenAiCompatibleProvider;
use App\Services\Empy\ProviderAdapter;
use App\Services\Empy\ProviderManager;
use App\Services\Empy\ProviderResponse;
use App\Services\Empy\WorkspaceReadableProvider;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class ProviderAdapterTest extends TestCase
{
    use RefreshDatabase;

    public function test_codex_cli_adapter_parses_structured_output_without_writing_the_workspace(): void
    {
        $script = tempnam(sys_get_temp_dir(), 'empy-codex-');
        $this->assertNotFalse($script);
        file_put_contents($script, <<<'SH'
#!/bin/sh
out=""
previous=""
for argument in "$@"; do
  if [ "$previous" = "--output-last-message" ]; then out="$argument"; fi
  previous="$argument"
done
cat > "$out" <<'JSON'
{"summary":"codex patch","files":[{"path":"index.html","content":"<main>codex</main>"}]}
JSON
exit 0
SH
        );
        chmod($script, 0700);
        config()->set('empy.codex.enabled', true);
        config()->set('empy.codex.binary', $script);
        config()->set('empy.codex.timeout', 10);

        try {
            $provider = new CodexCliProvider;
            $response = $provider->execute([
                'workspace_path' => sys_get_temp_dir(),
                'messages' => [['role' => 'user', 'content' => 'Return the assigned patch.']],
            ]);

            $this->assertSame('index.html', $response->files[0]['path']);
            $this->assertSame('<main>codex</main>', $response->files[0]['content']);
        } finally {
            @unlink($script);
        }
    }

    public function test_codex_workspace_read_prompt_uses_only_allowlisted_metadata_and_ephemeral_runs(): void
    {
        $script = tempnam(sys_get_temp_dir(), 'empy-codex-workspace-');
        $captureDirectory = sys_get_temp_dir().'/empy-codex-capture-'.bin2hex(random_bytes(6));
        $workspace = sys_get_temp_dir().'/empy-codex-workspace-'.bin2hex(random_bytes(6));
        $this->assertNotFalse($script);
        $this->assertTrue(mkdir($captureDirectory, 0700, true));
        $this->assertTrue(mkdir($workspace, 0700, true));
        $workspaceContent = '<main>workspace</main>';
        file_put_contents($workspace.'/index.html', $workspaceContent);
        $workspaceHash = hash('sha256', $workspaceContent);
        $scriptContents = str_replace('__CAPTURE__', $captureDirectory, <<<'SH'
#!/bin/sh
out=""
previous=""
for argument in "$@"; do
  if [ "$previous" = "--output-last-message" ]; then out="$argument"; fi
  previous="$argument"
done
capture="__CAPTURE__/$(basename "$(dirname "$out")").prompt"
cat > "$capture"
cat > "$out" <<'JSON'
{"summary":"codex patch","files":[{"path":"index.html","content":"<main>codex</main>"}]}
JSON
exit 0
SH
        );
        file_put_contents($script, $scriptContents);
        chmod($script, 0700);
        config()->set('empy.codex.enabled', true);
        config()->set('empy.codex.binary', $script);
        config()->set('empy.codex.timeout', 10);

        try {
            $manager = new ProviderManager([new CodexCliProvider]);
            $request = [
                'workspace_path' => $workspace,
                'inline_messages' => [['role' => 'user', 'content' => 'INLINE SECRET FILE CONTENT']],
                'workspace_messages' => [['role' => 'user', 'content' => 'Change the assigned file.']],
                'workspace_allowlist' => [['path' => 'index.html', 'sha256' => $workspaceHash]],
            ];

            $first = $manager->execute($request);
            $second = $manager->execute($request);

            $this->assertSame('workspace-read', $first->contextMode);
            $this->assertSame('workspace-read', $second->contextMode);
            $this->assertCount(2, glob($captureDirectory.'/*.prompt') ?: []);
            foreach (glob($captureDirectory.'/*.prompt') ?: [] as $promptPath) {
                $prompt = (string) file_get_contents($promptPath);
                $this->assertStringContainsString('index.html', $prompt);
                $this->assertStringContainsString('sha256: '.$workspaceHash, $prompt);
                $this->assertStringNotContainsString('INLINE SECRET FILE CONTENT', $prompt);
            }
        } finally {
            @unlink($script);
            foreach (glob($captureDirectory.'/*') ?: [] as $path) {
                @unlink($path);
            }
            @rmdir($captureDirectory);
            @unlink($workspace.'/index.html');
            @rmdir($workspace);
        }
    }

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

        $run = (new ProviderManager([new OllamaProvider]))->execute(['messages' => []]);

        $this->assertSame('ollama', $run->provider);
        $this->assertSame('index.html', $run->response->files[0]['path']);
        $this->assertSame(12, $run->response->usage['prompt_tokens']);
    }

    public function test_gemini_adapter_parses_structured_json_and_usage(): void
    {
        config()->set('empy.gemini.api_key', 'test-key');
        config()->set('empy.gemini.model', 'gemini-test');
        config()->set('empy.gemini.base_url', 'https://gemini.test/v1beta');
        Http::fake([
            'https://gemini.test/v1beta/models/gemini-test:generateContent' => Http::response([
                'candidates' => [[
                    'content' => ['parts' => [['text' => '{"summary":"gemini","files":[{"path":"index.html","content":"ok"}]}']]],
                ]],
                'usageMetadata' => ['promptTokenCount' => 14, 'candidatesTokenCount' => 8, 'totalTokenCount' => 22],
            ], 200),
        ]);

        $response = (new GeminiProvider)->execute([
            'messages' => [
                ['role' => 'system', 'content' => 'Return JSON.'],
                ['role' => 'user', 'content' => 'Change the assigned file.'],
            ],
        ]);

        $this->assertSame('index.html', $response->files[0]['path']);
        $this->assertSame(14, $response->usage['prompt_tokens']);
        Http::assertSent(fn ($request): bool => $request->hasHeader('x-goog-api-key', 'test-key'));
    }

    public function test_gemini_quota_failure_is_classified_for_fallback(): void
    {
        config()->set('empy.gemini.api_key', 'test-key');
        config()->set('empy.gemini.model', 'gemini-test');
        config()->set('empy.gemini.base_url', 'https://gemini.test/v1beta');
        Http::fake(['https://gemini.test/v1beta/models/gemini-test:generateContent' => Http::response([], 429)]);

        try {
            (new GeminiProvider)->execute(['messages' => [['role' => 'user', 'content' => 'Change it.']]]);
            $this->fail('Expected a quota failure.');
        } catch (EmpyProviderException $exception) {
            $this->assertSame('provider_quota', $exception->errorCode);
        }
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

        $run = (new ProviderManager([new OpenAiCompatibleProvider, new OllamaProvider]))->execute(['messages' => []]);

        $this->assertSame('ollama', $run->provider);
        $this->assertSame('failed', $run->attempts[0]['status']);
        $this->assertSame('succeeded', $run->attempts[1]['status']);
    }

    public function test_manager_exposes_provider_unavailable_without_making_a_model_call(): void
    {
        Http::fake();
        try {
            (new ProviderManager([new OllamaProvider, new OpenAiCompatibleProvider]))->execute(['messages' => []]);
            $this->fail('Expected provider_unavailable.');
        } catch (EmpyProviderException $exception) {
            $this->assertSame('provider_unavailable', $exception->errorCode);
            $this->assertCount(2, $exception->attempts);
            Http::assertNothingSent();
        }
    }

    public function test_stale_workspace_context_stops_before_an_inline_fallback_can_use_old_bytes(): void
    {
        $stale = new class implements ProviderAdapter, WorkspaceReadableProvider
        {
            public function id(): string
            {
                return 'stale-workspace';
            }

            public function configured(): bool
            {
                return true;
            }

            public function supportsWorkspaceRead(): bool
            {
                return true;
            }

            public function execute(array $request): ProviderResponse
            {
                throw new EmpyProviderException('stale workspace', 'provider_workspace_stale');
            }
        };
        $fallback = new class implements ProviderAdapter
        {
            public bool $called = false;

            public function id(): string
            {
                return 'inline-fallback';
            }

            public function configured(): bool
            {
                return true;
            }

            public function execute(array $request): ProviderResponse
            {
                $this->called = true;

                return new ProviderResponse([
                    ['path' => 'index.html', 'content' => 'stale'],
                ]);
            }
        };

        try {
            (new ProviderManager([$stale, $fallback]))->execute([
                'inline_messages' => [['role' => 'user', 'content' => 'old bytes']],
                'workspace_messages' => [['role' => 'user', 'content' => 'metadata']],
                'workspace_allowlist' => [['path' => 'index.html', 'sha256' => str_repeat('a', 64)]],
            ]);
            $this->fail('Expected a stale workspace failure.');
        } catch (EmpyProviderException $exception) {
            $this->assertSame('provider_workspace_stale', $exception->errorCode);
            $this->assertCount(1, $exception->attempts);
            $this->assertFalse($fallback->called);
        }
    }
}
