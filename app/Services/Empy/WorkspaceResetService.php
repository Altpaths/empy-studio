<?php

namespace App\Services\Empy;

use FilesystemIterator;
use InvalidArgumentException;
use RuntimeException;
use SplFileInfo;

final class WorkspaceResetService
{
    /**
     * @param  string|null  $storageRoot  Explicit storage root. When omitted, APP_STORAGE_PATH or Laravel's storage path is used.
     * @param  string|null  $dataRoot  Explicit writable data root containing the storage root and optional SQLite/settings files.
     */
    public function __construct(
        private readonly ?string $storageRoot = null,
        private readonly ?string $dataRoot = null,
    ) {}

    /**
     * Remove Empy's managed workspace state and recreate its required directories.
     *
     * @return array{root: string, storage_root: string, deleted: list<string>, recreated: list<string>, settings_kept: bool, dry_run: bool}
     */
    public function reset(bool $keepSettings = false, bool $dryRun = false): array
    {
        $layout = $this->layout();
        $targets = $this->targets($layout, $keepSettings);
        $deleted = [];
        $recreated = [];

        foreach ($targets['clear'] as $path) {
            if ($this->pathExists($path)) {
                $deleted[] = $path;
            }

            if (! $dryRun) {
                $this->clearDirectory($path, preserveGitignore: true);
            }
        }

        foreach ($targets['delete'] as $path) {
            if ($this->pathExists($path)) {
                $deleted[] = $path;
            }

            if (! $dryRun && $this->pathExists($path)) {
                $this->removePath($path);
            }
        }

        foreach ($targets['recreate'] as $path) {
            if (! is_dir($path)) {
                $recreated[] = $path;
            }

            if (! $dryRun) {
                $this->ensureDirectory($path);
            }
        }

        if (! $dryRun && $targets['database'] !== null) {
            $database = $targets['database'];
            if (! is_file($database) && ! touch($database)) {
                throw new RuntimeException('The workspace database could not be recreated.');
            }
        }

        return [
            'root' => $layout['data'],
            'storage_root' => $layout['storage'],
            'deleted' => array_values(array_unique($deleted)),
            'recreated' => array_values(array_unique($recreated)),
            'settings_kept' => $keepSettings,
            'dry_run' => $dryRun,
        ];
    }

    /**
     * @return array{data: string, storage: string}
     */
    private function layout(): array
    {
        $this->rejectExplicitEmptyRoot($this->dataRoot, 'data');
        $this->rejectExplicitEmptyRoot($this->storageRoot, 'storage');

        $configuredDataValue = config('empy.data_root');
        if ($configuredDataValue !== null) {
            $this->rejectExplicitEmptyRoot(is_string($configuredDataValue) ? $configuredDataValue : null, 'data');
        }
        $configuredStorageValue = config('empy.storage_root');
        if ($configuredStorageValue !== null) {
            $this->rejectExplicitEmptyRoot(is_string($configuredStorageValue) ? $configuredStorageValue : null, 'storage');
        }
        $environmentDataRoot = getenv('EMPY_DATA_ROOT');
        if ($environmentDataRoot !== false) {
            $this->rejectExplicitEmptyRoot($environmentDataRoot, 'data');
        }
        $environmentStorageRoot = getenv('APP_STORAGE_PATH');
        if ($environmentStorageRoot !== false) {
            $this->rejectExplicitEmptyRoot($environmentStorageRoot, 'storage');
        }

        $configuredDataRoot = $this->firstConfigured([
            $this->dataRoot,
            config('empy.data_root'),
            $environmentDataRoot === false ? null : $environmentDataRoot,
        ]);
        $configuredStorageRoot = $this->firstConfigured([
            $this->storageRoot,
            config('empy.storage_root'),
            $environmentStorageRoot === false ? null : $environmentStorageRoot,
        ]);

        if ($configuredDataRoot !== null) {
            $data = $this->safeRoot($configuredDataRoot, 'data');
            $storage = $configuredStorageRoot !== null
                ? $this->safeRoot($configuredStorageRoot, 'storage')
                : $this->storageForDataRoot($data);
        } elseif ($configuredStorageRoot !== null) {
            $storage = $this->safeRoot($configuredStorageRoot, 'storage');
            $data = $this->dataForStorageRoot($storage);
        } else {
            $storage = $this->safeRoot(storage_path(), 'storage');
            $data = $this->dataForStorageRoot($storage);
        }

        // A separately configured storage path must remain within its configured
        // data root. This prevents a typo from turning reset into a cross-tree
        // deletion operation while still allowing the normal storage/data layout.
        if (! $this->isWithin($storage, $data) && ! $this->isWithin($data, $storage)) {
            throw new InvalidArgumentException('The configured storage and data roots must share a managed root.');
        }

        return ['data' => $data, 'storage' => $storage];
    }

    private function rejectExplicitEmptyRoot(?string $root, string $kind): void
    {
        if ($root !== null && trim($root) === '') {
            throw new InvalidArgumentException("The configured {$kind} root is empty or invalid.");
        }
    }

    /**
     * @param  array<int, mixed>  $values
     */
    private function firstConfigured(array $values): ?string
    {
        foreach ($values as $value) {
            if (is_string($value) && trim($value) !== '') {
                return trim($value);
            }
        }

        return null;
    }

    private function storageForDataRoot(string $dataRoot): string
    {
        if (basename($dataRoot) === 'storage') {
            return $dataRoot;
        }

        $nestedStorage = $dataRoot.DIRECTORY_SEPARATOR.'storage';
        if (is_dir($nestedStorage) || $this->looksLikeApplicationStorage($dataRoot)) {
            return $nestedStorage;
        }

        return $dataRoot;
    }

    private function dataForStorageRoot(string $storageRoot): string
    {
        return basename($storageRoot) === 'storage'
            ? dirname($storageRoot)
            : $storageRoot;
    }

    private function looksLikeApplicationStorage(string $root): bool
    {
        return is_dir($root.DIRECTORY_SEPARATOR.'app')
            || is_dir($root.DIRECTORY_SEPARATOR.'framework')
            || is_dir($root.DIRECTORY_SEPARATOR.'logs');
    }

    /**
     * @param  array{data: string, storage: string}  $layout
     * @return array{clear: list<string>, delete: list<string>, recreate: list<string>, database: string|null}
     */
    private function targets(array $layout, bool $keepSettings): array
    {
        $storage = $layout['storage'];
        $data = $layout['data'];

        $clear = [
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'private'.DIRECTORY_SEPARATOR.'empy',
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'public'.DIRECTORY_SEPARATOR.'empy',
            // These names were used by early desktop imports. Keep them in the
            // allowlist so old imports cannot survive a workspace reset.
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'private'.DIRECTORY_SEPARATOR.'imports',
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'private'.DIRECTORY_SEPARATOR.'project-imports',
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'private'.DIRECTORY_SEPARATOR.'historical-imports',
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'private'.DIRECTORY_SEPARATOR.'empy-imports',
            $storage.DIRECTORY_SEPARATOR.'framework'.DIRECTORY_SEPARATOR.'cache',
            $storage.DIRECTORY_SEPARATOR.'framework'.DIRECTORY_SEPARATOR.'sessions',
            $storage.DIRECTORY_SEPARATOR.'framework'.DIRECTORY_SEPARATOR.'views',
            $storage.DIRECTORY_SEPARATOR.'logs',
        ];

        // The normal desktop data root is outside the bundled source tree.
        // When running from a checkout, keep the source root's unrelated
        // top-level directories and only clear the known storage subtrees.
        if ($data !== $this->normalizePath(base_path())) {
            $clear = array_merge($clear, [
                $data.DIRECTORY_SEPARATOR.'projects',
                $data.DIRECTORY_SEPARATOR.'deliveries',
                $data.DIRECTORY_SEPARATOR.'imports',
                $data.DIRECTORY_SEPARATOR.'project-imports',
                $data.DIRECTORY_SEPARATOR.'historical-imports',
                $data.DIRECTORY_SEPARATOR.'empy-imports',
            ]);
        }

        foreach ($this->configuredDirectories() as $path) {
            if ($this->isWithinManagedStorage($path, $layout)) {
                $clear[] = $path;
            }
        }

        $clear = $this->uniquePaths($clear);
        $delete = [];
        if ($data !== $this->normalizePath(base_path())) {
            if (! $keepSettings) {
                $delete[] = $data.DIRECTORY_SEPARATOR.'.env';
            }
            foreach ([$data.DIRECTORY_SEPARATOR.'.env.backup', $data.DIRECTORY_SEPARATOR.'.env.previous'] as $settingsBackup) {
                if (! $keepSettings) {
                    $delete[] = $settingsBackup;
                }
            }
            foreach (['server.log', 'migrate.log', 'server.pid'] as $runtimeFile) {
                $delete[] = $data.DIRECTORY_SEPARATOR.$runtimeFile;
            }
        }

        foreach ($this->configuredFiles() as $path) {
            if ($this->isWithinManagedStorage($path, $layout)) {
                $delete[] = $path;
            }
        }

        $database = $this->databasePath($layout);
        if ($database !== null) {
            $delete[] = $database;
        }

        $recreate = [
            $storage,
            $storage.DIRECTORY_SEPARATOR.'app',
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'private',
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'private'.DIRECTORY_SEPARATOR.'empy',
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'public',
            $storage.DIRECTORY_SEPARATOR.'app'.DIRECTORY_SEPARATOR.'public'.DIRECTORY_SEPARATOR.'empy',
            $storage.DIRECTORY_SEPARATOR.'framework',
            $storage.DIRECTORY_SEPARATOR.'framework'.DIRECTORY_SEPARATOR.'cache',
            $storage.DIRECTORY_SEPARATOR.'framework'.DIRECTORY_SEPARATOR.'sessions',
            $storage.DIRECTORY_SEPARATOR.'framework'.DIRECTORY_SEPARATOR.'views',
            $storage.DIRECTORY_SEPARATOR.'logs',
        ];

        if ($database !== null) {
            $databaseDirectory = dirname($database);
            if ($databaseDirectory !== $data && ! $this->isWithinManagedRoots($databaseDirectory, $layout)) {
                $recreate[] = $databaseDirectory;
            }
        }

        return [
            'clear' => $clear,
            'delete' => $this->uniquePaths($delete),
            'recreate' => $this->uniquePaths($recreate),
            'database' => $database,
        ];
    }

    /**
     * @return list<string>
     */
    private function configuredDirectories(): array
    {
        $paths = [];
        $fileStore = config('cache.stores.file');
        if (is_array($fileStore)) {
            foreach (['path', 'lock_path'] as $key) {
                if (is_string($fileStore[$key] ?? null)) {
                    $paths[] = $fileStore[$key];
                }
            }
        }

        if (is_string(config('session.files'))) {
            $paths[] = (string) config('session.files');
        }

        return $paths;
    }

    /**
     * @return list<string>
     */
    private function configuredFiles(): array
    {
        $paths = [];
        $channels = config('logging.channels', []);
        if (is_array($channels)) {
            foreach ($channels as $channel) {
                if (is_array($channel) && is_string($channel['path'] ?? null)) {
                    $paths[] = $channel['path'];
                }
            }
        }

        return $paths;
    }

    /**
     * @param  array{data: string, storage: string}  $layout
     */
    private function databasePath(array $layout): ?string
    {
        $connectionName = config('database.default');
        $connection = config('database.connections.'.$connectionName);
        if (! is_array($connection) || ($connection['driver'] ?? null) !== 'sqlite') {
            return null;
        }

        $database = $connection['database'] ?? null;
        if (! is_string($database) || trim($database) === '' || $database === ':memory:') {
            return null;
        }

        $database = trim($database);
        if (! $this->isAbsolute($database)) {
            $database = base_path($database);
        }
        $database = $this->normalizePath($database);

        // A SQLite connection is only reset when its file is under the same
        // configured data/storage roots. External databases are left untouched.
        return $this->isWithinManagedRoots($database, $layout) ? $database : null;
    }

    /**
     * @param  array{data: string, storage: string}  $layout
     */
    private function isWithinManagedRoots(string $path, array $layout): bool
    {
        $path = $this->normalizePath($path);

        return $this->isWithin($path, $layout['data']) || $this->isWithin($path, $layout['storage']);
    }

    /**
     * Configured cache/log paths are user supplied values. Keep them inside a
     * storage child so a malformed setting cannot make reset clear the whole
     * writable data root.
     *
     * @param  array{data: string, storage: string}  $layout
     */
    private function isWithinManagedStorage(string $path, array $layout): bool
    {
        $path = $this->normalizePath($path);
        $storage = $this->normalizePath($layout['storage']);

        return $path !== $storage && $this->isWithin($path, $storage);
    }

    private function safeRoot(string $root, string $kind): string
    {
        $root = trim($root);
        if ($root === '' || str_contains($root, "\0")) {
            throw new InvalidArgumentException("The configured {$kind} root is empty or invalid.");
        }
        if (! $this->isAbsolute($root)) {
            throw new InvalidArgumentException("The configured {$kind} root must be an absolute path.");
        }

        $normalized = $this->canonicalPath($this->normalizePath($root));

        $home = getenv('HOME') ?: (function_exists('home_path') ? home_path() : '');
        $base = base_path();
        $broadRoots = [
            DIRECTORY_SEPARATOR.'tmp',
            DIRECTORY_SEPARATOR.'private'.DIRECTORY_SEPARATOR.'tmp',
            DIRECTORY_SEPARATOR.'var',
            DIRECTORY_SEPARATOR.'private',
            DIRECTORY_SEPARATOR.'Users',
            DIRECTORY_SEPARATOR.'home',
        ];
        if ($normalized === DIRECTORY_SEPARATOR
            || ($home !== '' && $normalized === $this->normalizePath($home))
            || $normalized === $this->normalizePath($base)
            || in_array($normalized, array_map([$this, 'normalizePath'], $broadRoots), true)
            || is_link($root)) {
            throw new InvalidArgumentException("The configured {$kind} root is unsafe for a workspace reset.");
        }

        return rtrim($normalized, DIRECTORY_SEPARATOR);
    }

    private function canonicalPath(string $path): string
    {
        $real = realpath($path);
        if ($real !== false) {
            return $this->normalizePath($real);
        }

        $parts = [];
        $cursor = $path;
        while (realpath($cursor) === false && $cursor !== dirname($cursor)) {
            $parts[] = basename($cursor);
            $cursor = dirname($cursor);
        }
        $realParent = realpath($cursor);
        if ($realParent === false) {
            return $path;
        }

        $canonical = $this->normalizePath($realParent);
        foreach (array_reverse($parts) as $part) {
            $canonical = rtrim($canonical, DIRECTORY_SEPARATOR).DIRECTORY_SEPARATOR.$part;
        }

        return $this->normalizePath($canonical);
    }

    private function normalizePath(string $path): string
    {
        $path = str_replace(['/', '\\'], DIRECTORY_SEPARATOR, $path);
        $prefix = '';
        if (DIRECTORY_SEPARATOR === '\\' && preg_match('/^[A-Za-z]:'.preg_quote(DIRECTORY_SEPARATOR, '/').'?/', $path, $match) === 1) {
            $prefix = $match[0];
            $path = substr($path, strlen($prefix));
        } elseif (str_starts_with($path, DIRECTORY_SEPARATOR)) {
            $prefix = DIRECTORY_SEPARATOR;
            $path = ltrim($path, DIRECTORY_SEPARATOR);
        }

        $parts = [];
        foreach (explode(DIRECTORY_SEPARATOR, $path) as $part) {
            if ($part === '' || $part === '.') {
                continue;
            }
            if ($part === '..') {
                if ($parts === []) {
                    throw new InvalidArgumentException('The configured workspace root contains path traversal.');
                }
                array_pop($parts);

                continue;
            }
            $parts[] = $part;
        }

        return $prefix.(implode(DIRECTORY_SEPARATOR, $parts) ?: ($prefix === DIRECTORY_SEPARATOR ? '' : '.'));
    }

    private function isAbsolute(string $path): bool
    {
        return str_starts_with($path, DIRECTORY_SEPARATOR)
            || preg_match('/^[A-Za-z]:[\\\/]/', $path) === 1;
    }

    private function isWithin(string $path, string $root): bool
    {
        $path = rtrim($this->normalizePath($path), DIRECTORY_SEPARATOR);
        $root = rtrim($this->normalizePath($root), DIRECTORY_SEPARATOR);

        return $path === $root || str_starts_with($path, $root.DIRECTORY_SEPARATOR);
    }

    /**
     * @param  list<string>  $paths
     * @return list<string>
     */
    private function uniquePaths(array $paths): array
    {
        $result = [];
        $seen = [];
        foreach ($paths as $path) {
            $normalized = $this->normalizePath($path);
            if (isset($seen[$normalized])) {
                continue;
            }
            $seen[$normalized] = true;
            $result[] = $normalized;
        }

        return $result;
    }

    private function pathExists(string $path): bool
    {
        return file_exists($path) || is_link($path);
    }

    private function ensureDirectory(string $path): void
    {
        if (is_dir($path)) {
            return;
        }
        if (is_link($path) || (file_exists($path) && ! is_dir($path))) {
            $this->removePath($path);
        }
        if (! mkdir($path, 0750, true) && ! is_dir($path)) {
            throw new RuntimeException("The workspace directory {$path} could not be created.");
        }
    }

    private function clearDirectory(string $path, bool $preserveGitignore): void
    {
        if (is_link($path) || (file_exists($path) && ! is_dir($path))) {
            $this->removePath($path);
        }
        $this->ensureDirectory($path);

        $iterator = new FilesystemIterator($path, FilesystemIterator::SKIP_DOTS);
        foreach ($iterator as $item) {
            /** @var SplFileInfo $item */
            if ($preserveGitignore && $item->getFilename() === '.gitignore') {
                continue;
            }
            if ($preserveGitignore && $item->isDir() && ! $item->isLink()) {
                $this->clearDirectory($item->getPathname(), true);

                continue;
            }
            $this->removePath($item->getPathname());
        }
    }

    private function removePath(string $path): void
    {
        if (is_link($path) || is_file($path)) {
            if (! unlink($path) && $this->pathExists($path)) {
                throw new RuntimeException("The workspace path {$path} could not be removed.");
            }

            return;
        }
        if (! is_dir($path)) {
            return;
        }

        $iterator = new FilesystemIterator($path, FilesystemIterator::SKIP_DOTS);
        foreach ($iterator as $item) {
            /** @var SplFileInfo $item */
            $this->removePath($item->getPathname());
        }
        if (! rmdir($path) && is_dir($path)) {
            throw new RuntimeException("The workspace directory {$path} could not be removed.");
        }
    }
}
