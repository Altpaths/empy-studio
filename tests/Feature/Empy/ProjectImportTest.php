<?php

namespace Tests\Feature\Empy;

use App\Models\Project;
use App\Services\Empy\ProjectImportService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;
use ZipArchive;

class ProjectImportTest extends TestCase
{
    use RefreshDatabase;

    public function test_projects_collection_url_returns_the_dashboard(): void
    {
        $response = $this->get('/projects');

        $response->assertOk();
        $response->assertSee('پروژهٔ جدید');
    }

    public function test_import_isolated_project_builds_manifest_without_unrelated_files(): void
    {
        $archive = $this->archive([
            'public/index.html' => '<main>hello</main>',
            'composer.json' => '{"require":{"php":"^8.3"}}',
            '.empy/old-ticket.json' => 'must not be indexed',
            'vendor/old-package.php' => '<?php',
        ]);

        $project = app(ProjectImportService::class)->import($archive, 'demo');

        $this->assertSame('ready', $project->status);
        $this->assertSame(['php', 'static-site'], $project->manifest['frameworks']);
        $this->assertSame(['composer.json', 'public/index.html'], $project->manifest['entry_points']);
        $paths = array_column($project->manifest['files'], 'path');
        $this->assertSame(['composer.json', 'public/index.html'], $paths);
        $this->assertCount(1, Project::query()->get());
    }

    public function test_path_traversal_is_rejected_and_project_is_not_left_behind(): void
    {
        $archive = $this->archive(['../../outside.txt' => 'bad']);

        $this->expectExceptionMessage('path traversal');
        app(ProjectImportService::class)->import($archive);

        $this->assertDatabaseCount('projects', 0);
    }

    /** @param array<string, string> $files */
    private function archive(array $files): string
    {
        $path = tempnam(sys_get_temp_dir(), 'empy-zip-');
        $zip = new ZipArchive;
        $this->assertTrue($zip->open($path, ZipArchive::CREATE | ZipArchive::OVERWRITE));
        foreach ($files as $name => $contents) {
            $zip->addFromString($name, $contents);
        }
        $zip->close();

        return $path;
    }
}
