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
use App\Services\Empy\TicketPlanner;
use App\Services\Empy\VerificationService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Storage;
use Tests\TestCase;
use ZipArchive;

class TicketBaselineTest extends TestCase
{
    use RefreshDatabase;

    public function test_sequential_tickets_use_their_own_baselines_and_advance_the_project_manifest(): void
    {
        Storage::fake('local');
        $project = app(ProjectImportService::class)->import($this->archive([
            'index.html' => '<main>Home</main>',
            'about.html' => '<main>About</main>',
        ]), 'Demo Site');

        $first = Ticket::create([
            'project_id' => $project->id,
            'title' => 'Update home',
            'request_text' => 'Change index.html heading',
        ]);
        app(TicketPlanner::class)->plan($first);
        $this->assertSame($project->manifest, $first->fresh()->baseline_manifest);
        $this->execute($first->fresh(), [
            ['path' => 'index.html', 'content' => '<main>Updated home</main>'],
        ]);

        $firstVerification = app(VerificationService::class)->verify($first->fresh());
        $this->assertSame(['index.html'], $firstVerification['changed_files']);
        $projectAfterFirst = $project->fresh();
        $this->assertSame($this->hashFor($projectAfterFirst->manifest, 'index.html'), hash('sha256', '<main>Updated home</main>'));

        $second = Ticket::create([
            'project_id' => $project->id,
            'title' => 'Update about page',
            'request_text' => 'Change about.html heading',
        ]);
        app(TicketPlanner::class)->plan($second);
        $this->assertSame($projectAfterFirst->manifest, $second->fresh()->baseline_manifest);
        $this->execute($second->fresh(), [
            ['path' => 'about.html', 'content' => '<main>Updated about</main>'],
        ]);

        $secondVerification = app(VerificationService::class)->verify($second->fresh());
        $this->assertSame(['about.html'], $secondVerification['changed_files']);
        $this->assertSame('verified', $second->fresh()->status);
        $this->assertSame($this->hashFor($project->fresh()->manifest, 'about.html'), hash('sha256', '<main>Updated about</main>'));
    }

    public function test_legacy_ticket_without_a_baseline_falls_back_to_the_project_manifest(): void
    {
        Storage::fake('local');
        $project = app(ProjectImportService::class)->import($this->archive([
            'index.html' => '<main>Home</main>',
        ]), 'Demo Site');
        $ticket = Ticket::create([
            'project_id' => $project->id,
            'title' => 'Update home',
            'request_text' => 'Change index.html heading',
        ]);
        app(TicketPlanner::class)->plan($ticket);
        $ticket->update(['baseline_manifest' => null]);
        $this->execute($ticket->fresh(), [
            ['path' => 'index.html', 'content' => '<main>Updated</main>'],
        ]);

        $verification = app(VerificationService::class)->verify($ticket->fresh());

        $this->assertSame(['index.html'], $verification['changed_files']);
        $this->assertSame('verified', $ticket->fresh()->status);
    }

    /** @param list<array{path: string, content: string}> $files */
    private function execute(Ticket $ticket, array $files): void
    {
        $run = (new ExecutionService(
            app(ContextLedger::class),
            new ProviderManager([new TicketBaselineFakeProvider(new ProviderResponse($files, 'updated'))]),
            app(PatchApplier::class),
        ))->execute($ticket);

        $this->assertSame('succeeded', $run->status);
    }

    /** @param array<string, mixed> $manifest */
    private function hashFor(array $manifest, string $path): string
    {
        foreach ($manifest['files'] ?? [] as $file) {
            if (($file['path'] ?? null) === $path) {
                return (string) ($file['sha256'] ?? '');
            }
        }

        return '';
    }

    /** @param array<string, string> $files */
    private function archive(array $files): string
    {
        $path = tempnam(sys_get_temp_dir(), 'empy-baseline-');
        $zip = new ZipArchive;
        $this->assertTrue($zip->open($path, ZipArchive::CREATE | ZipArchive::OVERWRITE));
        foreach ($files as $name => $contents) {
            $zip->addFromString($name, $contents);
        }
        $zip->close();

        return $path;
    }
}

final class TicketBaselineFakeProvider implements ProviderAdapter
{
    public function __construct(private readonly ProviderResponse $response) {}

    public function id(): string
    {
        return 'ticket-baseline-fake';
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
