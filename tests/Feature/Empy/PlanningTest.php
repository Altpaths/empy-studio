<?php

namespace Tests\Feature\Empy;

use App\Exceptions\EmpyPlanningException;
use App\Models\Ticket;
use App\Services\Empy\AgentPlanValidator;
use App\Services\Empy\ContextLedger;
use App\Services\Empy\ProjectImportService;
use App\Services\Empy\TicketPlanner;
use App\Support\Empy\PathGuard;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Storage;
use Tests\TestCase;
use ZipArchive;

class PlanningTest extends TestCase
{
    use RefreshDatabase;

    public function test_homepage_ticket_gets_one_owned_frontend_node_and_compact_context(): void
    {
        Storage::fake('local');
        $project = app(ProjectImportService::class)->import($this->archive([
            'public/index.html' => '<h1>Home</h1>',
            'about.html' => '<h1>About</h1>',
        ]), 'site');
        $ticket = Ticket::create([
            'project_id' => $project->id,
            'title' => 'Homepage visual change',
            'request_text' => 'برای صفحه اول یک نمودار اضافه کن',
        ]);

        $plan = app(TicketPlanner::class)->plan($ticket);
        $context = app(ContextLedger::class)->build($project, $plan);

        $this->assertSame('planned', $ticket->fresh()->status);
        $this->assertCount(1, $plan['nodes']);
        $this->assertSame('public/index.html', $plan['nodes'][0]['writer']);
        $this->assertSame('frontend', $plan['nodes'][0]['role']);
        $this->assertSame(1, $context['stats']['files']);
        $this->assertSame(1, $context['stats']['unique_files']);
        $this->assertStringContainsString('Home', $context['items'][0]['content']);
    }

    public function test_unknown_explicit_target_fails_before_provider_execution(): void
    {
        Storage::fake('local');
        $project = app(ProjectImportService::class)->import($this->archive([
            'index.html' => '<main>Home</main>',
        ]), 'site');
        $ticket = Ticket::create([
            'project_id' => $project->id,
            'title' => 'Missing target',
            'request_text' => 'Change missing/page.html',
        ]);

        $this->expectException(EmpyPlanningException::class);
        $this->expectExceptionCode('target_not_found');
        app(TicketPlanner::class)->plan($ticket);
    }

    public function test_validator_rejects_duplicate_writers(): void
    {
        Storage::fake('local');
        $project = app(ProjectImportService::class)->import($this->archive([
            'index.html' => '<main>Home</main>',
        ]), 'site');

        $this->expectExceptionCode('duplicate_writer');
        app(AgentPlanValidator::class)->validate($project, [
            'nodes' => [
                ['id' => 'one', 'writer' => 'index.html', 'files' => ['index.html']],
                ['id' => 'two', 'writer' => 'index.html', 'files' => ['index.html']],
            ],
        ]);
    }

    /** @param array<string, string> $files */
    private function archive(array $files): string
    {
        $path = tempnam(sys_get_temp_dir(), 'empy-plan-');
        $zip = new ZipArchive();
        $this->assertTrue($zip->open($path, ZipArchive::CREATE | ZipArchive::OVERWRITE));
        foreach ($files as $name => $contents) {
            $zip->addFromString($name, $contents);
        }
        $zip->close();

        return $path;
    }
}
