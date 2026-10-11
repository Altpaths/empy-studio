<?php

namespace Tests\Feature\Empy;

use App\Models\Ticket;
use App\Services\Empy\ContextLedger;
use App\Services\Empy\ExecutionService;
use App\Services\Empy\PatchApplier;
use App\Services\Empy\ProjectImportService;
use App\Services\Empy\ProviderAdapter;
use App\Services\Empy\ProviderManager;
use App\Services\Empy\ProviderResponse;
use App\Services\Empy\RecoveryService;
use App\Services\Empy\TicketPlanner;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Storage;
use Tests\TestCase;
use ZipArchive;

class RecoveryTest extends TestCase
{
    use RefreshDatabase;

    public function test_recovery_changes_the_graph_before_a_second_provider_call(): void
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
        $provider = new SequenceProvider([
            new ProviderResponse([['path' => 'index.html', 'content' => '<main>Home</main>']], 'unchanged'),
            new ProviderResponse([['path' => 'index.html', 'content' => '<main>Recovered</main>']], 'changed'),
        ]);
        $execution = new ExecutionService(app(ContextLedger::class), new ProviderManager([$provider]), app(PatchApplier::class));
        $first = $execution->execute($ticket->fresh('project'));
        $this->assertSame('failed', $first->status);
        $oldFingerprint = $first->graph_fingerprint;

        $this->assertTrue(app(RecoveryService::class)->prepareNextAttempt($ticket->fresh('project'), $first));
        $second = $execution->execute($ticket->fresh('project'));

        $this->assertSame('succeeded', $second->status);
        $this->assertNotSame($oldFingerprint, $second->graph_fingerprint);
        $this->assertSame('executed', $ticket->fresh()->status);
        $this->assertSame('<main>Recovered</main>', Storage::disk('local')->get($project->source_path.'/index.html'));
        $this->assertSame(2, $ticket->runs()->count());
    }

    /** @param array<string, string> $files */
    private function archive(array $files): string
    {
        $path = tempnam(sys_get_temp_dir(), 'empy-recovery-');
        $zip = new ZipArchive;
        $this->assertTrue($zip->open($path, ZipArchive::CREATE | ZipArchive::OVERWRITE));
        foreach ($files as $name => $contents) {
            $zip->addFromString($name, $contents);
        }
        $zip->close();

        return $path;
    }
}

final class SequenceProvider implements ProviderAdapter
{
    /** @param list<ProviderResponse> $responses */
    public function __construct(private array $responses) {}

    public function id(): string
    {
        return 'sequence';
    }

    public function configured(): bool
    {
        return true;
    }

    public function execute(array $request): ProviderResponse
    {
        return array_shift($this->responses) ?? new ProviderResponse([
            ['path' => 'index.html', 'content' => '<main>Recovered again</main>'],
        ], 'fallback');
    }
}
