<?php

use App\Services\Empy\WorkspaceResetService;
use Illuminate\Foundation\Inspiring;
use Illuminate\Support\Facades\Artisan;

Artisan::command('inspire', function () {
    $this->comment(Inspiring::quote());
})->purpose('Display an inspiring quote');

Artisan::command('empy:reset-workspace
    {--force : Confirm that all managed workspace data may be deleted}
    {--keep-settings : Preserve the writable data root .env settings file}
    {--dry-run : Show the managed paths that would be changed without deleting anything}', function () {
    if (! $this->option('force')) {
        $this->error('Refusing to reset the workspace without --force. This permanently deletes managed project data.');

        return 1;
    }

    $dryRun = (bool) $this->option('dry-run');
    $keepSettings = (bool) $this->option('keep-settings');
    $this->warn($dryRun
        ? 'Dry run: no workspace data will be changed.'
        : 'This permanently deletes Empy projects, deliveries, database state, cache, and logs under the configured data root.');

    try {
        /** @var WorkspaceResetService $reset */
        $reset = app(WorkspaceResetService::class);
        $result = $reset->reset($keepSettings, $dryRun);
    } catch (Throwable $exception) {
        $this->error($exception->getMessage());

        return 1;
    }

    $this->line(($dryRun ? 'Would reset' : 'Reset').' workspace root: '.$result['root']);
    if ($keepSettings) {
        $this->line('Settings: preserved (--keep-settings).');
    }
    $this->line('Managed running processes were not stopped.');
    $this->info($dryRun ? 'Dry run complete.' : 'Workspace reset complete.');

    return 0;
})->purpose('Safely clear Empy-managed workspace data and recreate required directories');
