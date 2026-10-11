<?php

namespace Tests\Feature\Empy;

use App\Models\Ticket;
use App\Services\Empy\AgentPlanValidator;
use App\Services\Empy\ContextLedger;
use App\Services\Empy\ExecutionService;
use App\Services\Empy\OllamaProvider;
use App\Services\Empy\OpenAiCompatibleProvider;
use App\Services\Empy\PatchApplier;
use App\Services\Empy\ProviderAdapter;
use App\Services\Empy\ProviderManager;
use App\Services\Empy\ProviderResponse;
use App\Services\Empy\ProjectImportService;
use App\Services\Empy\TicketPlanner;
use App\Support\Empy\PathGuard;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Storage;
use Tests\TestCase;
use ZipArchive;

class ExecutionTest extends TestCase
{
    use RefreshDatabase;

    public function test_structured_provider_patch_changes_only_the_owned_file(): void
    {
        Storage::fake('local');
        $project = app(ProjectImportService::class)->import($this->archive([
            'index.html' => '<main>Home</main>',
        ]), 'site');
        $ticket = Ticket::create([
            'project_id' => $project->id,
            'title' => 'Change heading',
            'request_text' => 'Change index.html heading',
        ]);
        app(TicketPlanner::class)->plan($ticket);
        $provider = new FakeProvider(new ProviderResponse([
            ['path' => 'index.html', 'content' => '<main>Updated</main>'],
        ], 'Updated heading'));

        $run = $this->executor(new ProviderManager([$provider]))->execute($ticket->fresh());

        $this->assertSame('succeeded', $run->status);
        $this->assertSame('executed', $ticket->fresh()->status);
        $this->assertSame(['index.html'], $ticket->fresh()->result['changed_files']);
        $this->assertSame('<main>Updated</main>', Storage::disk('local')->get($project->source_path.'/index.html'));
        $this->assertSame(1, $run->context_stats['unique_files']);
    }

    public function test_no_configured_provider_is_a_clear_failure_without_a_file_change(): void
    {
        Storage::fake('local');
        $project = app(ProjectImportService::class)->import($this->archive([
            'index.html' => '<main>Home</main>',
        ]), 'site');
        $ticket = Ticket::create([
            'project_id' => $project->id,
            'title' => 'Change heading',
            'request_text' => 'Change index.html heading',
        ]);
        app(TicketPlanner::class)->plan($ticket);

        $run = $this->executor(new ProviderManager([
            new OllamaProvider(),
            new OpenAiCompatibleProvider(),
        ]))->execute($ticket->fresh());

        $this->assertSame('failed', $run->status);
        $this->assertSame('provider_unavailable', $ticket->fresh()->failure_code);
        $this->assertStringContainsString('Provider', $ticket->fresh()->failure_detail);
        $this->assertSame('<main>Home</main>', Storage::disk('local')->get($project->source_path.'/index.html'));
        $event = $run->events()->where('kind', 'run_failed')->firstOrFail();
        $this->assertSame('provider_unavailable', $event->payload['code']);
    }

    public function test_provider_cannot_write_outside_its_assigned_target(): void
    {
        Storage::fake('local');
        $project = app(ProjectImportService::class)->import($this->archive([
            'index.html' => '<main>Home</main>',
            'secret.txt' => 'unchanged',
        ]), 'site');
        $ticket = Ticket::create([
            'project_id' => $project->id,
            'title' => 'Change heading',
            'request_text' => 'Change index.html heading',
        ]);
        app(TicketPlanner::class)->plan($ticket);
        $provider = new FakeProvider(new ProviderResponse([
            ['path' => 'secret.txt', 'content' => 'tampered'],
        ], 'bad'));

        $run = $this->executor(new ProviderManager([$provider]))->execute($ticket->fresh());

        $this->assertSame('failed', $run->status);
        $this->assertSame('out_of_scope_write', $ticket->fresh()->failure_code);
        $this->assertSame('unchanged', Storage::disk('local')->get($project->source_path.'/secret.txt'));
    }

    private function executor(ProviderManager $providers): ExecutionService
    {
        return new ExecutionService(
            app(ContextLedger::class),
            $providers,
            app(PatchApplier::class),
        );
    }

    /** @param array<string, string> $files */
    private function archive(array $files): string
    {
        $path = tempnam(sys_get_temp_dir(), 'empy-execution-');
        $zip = new ZipArchive();
        $this->assertTrue($zip->open($path, ZipArchive::CREATE | ZipArchive::OVERWRITE));
        foreach ($files as $name => $contents) {
            $zip->addFromString($name, $contents);
        }
        $zip->close();

        return $path;
    }
}

final class FakeProvider implements ProviderAdapter
{
    public function __construct(private readonly ProviderResponse $response)
    {
    }

    public function id(): string
    {
        return 'fake';
    }

    public function configured(): bool
    {
        return true;
    }

    public function execute(array $request): ProviderResponse
    {
        return $this->response;
    }
}
