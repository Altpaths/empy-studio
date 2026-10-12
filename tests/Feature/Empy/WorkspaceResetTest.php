<?php

namespace Tests\Feature\Empy;

use App\Services\Empy\WorkspaceResetService;
use Illuminate\Support\Facades\File;
use Tests\TestCase;

class WorkspaceResetTest extends TestCase
{
    private string $root;

    protected function setUp(): void
    {
        parent::setUp();

        $this->root = sys_get_temp_dir().DIRECTORY_SEPARATOR.'empy-reset-'.bin2hex(random_bytes(8));
        File::makeDirectory($this->root, 0750, true);
        config([
            'empy.data_root' => $this->root,
            'empy.storage_root' => $this->root.DIRECTORY_SEPARATOR.'storage',
            'database.default' => 'sqlite',
            'database.connections.sqlite.database' => $this->root.DIRECTORY_SEPARATOR.'database.sqlite',
        ]);
    }

    protected function tearDown(): void
    {
        File::deleteDirectory($this->root);
        config([
            'empy.data_root' => null,
            'empy.storage_root' => null,
            'database.connections.sqlite.database' => ':memory:',
        ]);

        parent::tearDown();
    }

    public function test_reset_refuses_to_run_without_force(): void
    {
        $stale = $this->root.DIRECTORY_SEPARATOR.'storage/app/private/empy/projects/old.txt';
        File::ensureDirectoryExists(dirname($stale));
        File::put($stale, 'keep me');

        $this->artisan('empy:reset-workspace')
            ->expectsOutputToContain('--force')
            ->assertExitCode(1);

        $this->assertFileExists($stale);
    }

    public function test_service_refuses_an_empty_configured_root(): void
    {
        $this->expectException(\InvalidArgumentException::class);

        (new WorkspaceResetService(storageRoot: ''))->reset();
    }

    public function test_forced_reset_removes_managed_data_and_recreates_directories(): void
    {
        $storage = $this->root.DIRECTORY_SEPARATOR.'storage';
        $stalePaths = [
            $storage.'/app/private/empy/projects/old.txt',
            $storage.'/app/private/empy/deliveries/old.zip',
            $storage.'/app/private/empy/imports/old.json',
            $storage.'/framework/cache/data/old.cache',
            $storage.'/framework/sessions/old.session',
            $storage.'/framework/views/old.php',
            $storage.'/logs/laravel.log',
        ];
        foreach ($stalePaths as $path) {
            File::ensureDirectoryExists(dirname($path));
            File::put($path, 'stale');
        }
        File::put($this->root.DIRECTORY_SEPARATOR.'.env', 'APP_KEY=keep-or-remove');
        File::put($this->root.DIRECTORY_SEPARATOR.'database.sqlite', 'stale database');
        File::put($this->root.DIRECTORY_SEPARATOR.'unrelated.txt', 'leave me');

        $this->artisan('empy:reset-workspace', ['--force' => true])
            ->expectsOutputToContain('Workspace reset complete.')
            ->assertExitCode(0);

        foreach ($stalePaths as $path) {
            $this->assertFileDoesNotExist($path);
        }
        foreach ([
            $storage,
            $storage.'/app/private/empy',
            $storage.'/app/public',
            $storage.'/framework/cache',
            $storage.'/framework/sessions',
            $storage.'/framework/views',
            $storage.'/logs',
            $this->root.'/database.sqlite',
        ] as $path) {
            $this->assertFileExists($path);
        }
        $this->assertFileDoesNotExist($this->root.'/.env');
        $this->assertFileExists($this->root.'/unrelated.txt');
    }

    public function test_keep_settings_preserves_the_writable_env_file(): void
    {
        File::put($this->root.DIRECTORY_SEPARATOR.'.env', 'APP_KEY=preserve');

        $this->artisan('empy:reset-workspace', [
            '--force' => true,
            '--keep-settings' => true,
        ])->assertExitCode(0);

        $this->assertFileExists($this->root.'/.env');
        $this->assertSame('APP_KEY=preserve', File::get($this->root.'/.env'));
    }
}
