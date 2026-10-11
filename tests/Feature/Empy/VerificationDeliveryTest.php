<?php

namespace Tests\Feature\Empy;

use App\Models\Ticket;
use App\Services\Empy\ContextLedger;
use App\Services\Empy\DeliveryService;
use App\Services\Empy\ExecutionService;
use App\Services\Empy\PatchApplier;
use App\Services\Empy\ProviderManager;
use App\Services\Empy\ProviderResponse;
use App\Services\Empy\ProjectImportService;
use App\Services\Empy\TicketPlanner;
use App\Services\Empy\VerificationService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Storage;
use Tests\Feature\Empy\FakeProvider;
use Tests\TestCase;
use ZipArchive;

class VerificationDeliveryTest extends TestCase
{
    use RefreshDatabase;

    public function test_only_verified_project_can_be_delivered_and_zip_preserves_paths(): void
    {
        Storage::fake('local');
        $project = app(ProjectImportService::class)->import($this->archive([
            'index.html' => '<main>Home</main>',
            '.env' => 'SECRET=must-not-ship',
            'public/app.css' => 'body{}',
        ]), 'Demo Site');
        $ticket = Ticket::create([
            'project_id' => $project->id,
            'title' => 'Update home',
            'request_text' => 'Change index.html heading',
        ]);
        app(TicketPlanner::class)->plan($ticket);
        $run = (new ExecutionService(
            app(ContextLedger::class),
            new ProviderManager([new FakeProvider(new ProviderResponse([
                ['path' => 'index.html', 'content' => '<main>Updated</main>'],
            ], 'updated'))]),
            app(PatchApplier::class),
        ))->execute($ticket->fresh());
        $this->assertSame('succeeded', $run->status);

        $verification = app(VerificationService::class)->verify($ticket->fresh());
        $this->assertSame(['index.html'], $verification['changed_files']);
        $artifact = app(DeliveryService::class)->deliver($ticket->fresh());

        $this->assertSame('delivered', $ticket->fresh()->status);
        $this->assertFileExists(Storage::disk('local')->path($artifact->path));
        $zip = new ZipArchive();
        $this->assertTrue($zip->open(Storage::disk('local')->path($artifact->path)));
        $names = [];
        for ($index = 0; $index < $zip->numFiles; $index++) {
            $names[] = $zip->getNameIndex($index);
        }
        $this->assertContains('demo-site/index.html', $names);
        $this->assertContains('demo-site/public/app.css', $names);
        $this->assertNotContains('demo-site/.env', $names);
        $this->assertContains('demo-site/EMPy-MANIFEST.json', $names);
        $zip->close();
        $this->assertSame($artifact->sha256, hash_file('sha256', Storage::disk('local')->path($artifact->path)));
    }

    /** @param array<string, string> $files */
    private function archive(array $files): string
    {
        $path = tempnam(sys_get_temp_dir(), 'empy-delivery-');
        $zip = new ZipArchive();
        $this->assertTrue($zip->open($path, ZipArchive::CREATE | ZipArchive::OVERWRITE));
        foreach ($files as $name => $contents) {
            $zip->addFromString($name, $contents);
        }
        $zip->close();

        return $path;
    }
}
