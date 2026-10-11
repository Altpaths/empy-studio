<?php

namespace Tests\Feature\Empy;

use App\Models\Project;
use App\Models\Ticket;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Storage;
use Tests\TestCase;
use ZipArchive;

class ApplicationFlowTest extends TestCase
{
    use RefreshDatabase;

    public function test_dashboard_and_import_flow_are_available_without_a_provider(): void
    {
        Storage::fake('local');
        $this->get('/')
            ->assertOk()
            ->assertSee('پروژهٔ جدید')
            ->assertSee('project-import-form')
            ->assertSee('آن را در Downloads کپی کنید', false)
            ->assertSee('در حال بررسی خوانا بودن فایل', false)
            ->assertSee('ارسال فایل بیش از ۹۰ ثانیه', false);

        $response = $this->post('/projects', [
            'name' => 'Flow Site',
            'archive' => $this->uploadedZip(['index.html' => '<h1>Home</h1>']),
        ]);

        $project = Project::query()->firstOrFail();
        $response->assertRedirect(route('projects.show', $project));
        $this->assertSame('ready', $project->status);
        $this->get(route('projects.show', $project))->assertOk()->assertSee('Flow Site');
    }

    public function test_ticket_plan_and_clear_provider_failure_are_visible_in_the_ui(): void
    {
        Storage::fake('local');
        // This scenario intentionally verifies the no-provider boundary. The
        // product default includes Codex when it is available on the host.
        config()->set('empy.codex.enabled', false);
        $this->post('/projects', [
            'name' => 'Flow Site',
            'archive' => $this->uploadedZip(['index.html' => '<h1>Home</h1>']),
        ]);
        $project = Project::query()->firstOrFail();
        $response = $this->post(route('tickets.store', $project), [
            'title' => 'Change heading',
            'request_text' => 'Change index.html heading',
        ]);
        $ticket = Ticket::query()->firstOrFail();
        $response->assertRedirect()->assertSessionHas('success');
        $this->assertSame('planned', $ticket->status);

        $this->from(route('projects.show', $project))
            ->post(route('tickets.execute', $ticket))
            ->assertRedirect(route('projects.show', $project))
            ->assertSessionHas('error', fn (string $message): bool => str_contains($message, 'Provider آماده نیست'));
        $this->assertSame('provider_unavailable', $ticket->fresh()->failure_code);
        $this->get(route('projects.show', $project))->assertSee('Provider آماده نیست');
    }

    /** @param array<string, string> $files */
    private function uploadedZip(array $files): UploadedFile
    {
        $path = tempnam(sys_get_temp_dir(), 'empy-flow-');
        $zip = new ZipArchive;
        $this->assertTrue($zip->open($path, ZipArchive::CREATE | ZipArchive::OVERWRITE));
        foreach ($files as $name => $contents) {
            $zip->addFromString($name, $contents);
        }
        $zip->close();

        return UploadedFile::fake()->createWithContent('site.zip', (string) file_get_contents($path));
    }
}
