<?php

namespace App\Services\Empy;

use App\Support\Empy\PathGuard;
use FilesystemIterator;
use RecursiveCallbackFilterIterator;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use SplFileInfo;

final class ProjectIndexer
{
    public function __construct(private readonly PathGuard $paths) {}

    /** @return array{files: list<array<string, mixed>>, total_files: int, total_bytes: int, frameworks: list<string>, entry_points: list<string>} */
    public function index(string $root): array
    {
        $root = rtrim($root, DIRECTORY_SEPARATOR);
        $files = [];
        $frameworks = [];
        $entryPoints = [];
        $totalBytes = 0;

        $directory = new RecursiveDirectoryIterator(
            $root,
            FilesystemIterator::SKIP_DOTS | FilesystemIterator::CURRENT_AS_FILEINFO,
        );
        $filter = new RecursiveCallbackFilterIterator(
            $directory,
            function (SplFileInfo $current) use ($root): bool {
                $relative = ltrim(str_replace('\\', '/', substr($current->getPathname(), strlen($root))), '/');

                return ! $this->paths->isIgnored($relative);
            },
        );

        foreach (new RecursiveIteratorIterator($filter) as $file) {
            /** @var SplFileInfo $file */
            if (! $file->isFile() || $file->isLink()) {
                continue;
            }

            $relative = ltrim(str_replace('\\', '/', substr($file->getPathname(), strlen($root))), '/');
            if ($relative === '' || $this->paths->isIgnored($relative)) {
                continue;
            }

            $size = $file->getSize();
            $totalBytes += $size;
            $lower = strtolower($relative);
            $basename = strtolower($file->getBasename());
            $extension = strtolower($file->getExtension());
            $files[] = [
                'path' => $relative,
                'size' => $size,
                'sha256' => hash_file('sha256', $file->getPathname()),
                'extension' => $extension,
                'kind' => $this->kind($extension),
            ];

            if (in_array($basename, ['artisan', 'manage.py', 'go.mod', 'cargo.toml', 'composer.json', 'package.json', 'pyproject.toml'], true)) {
                $entryPoints[] = $relative;
            }
            if (in_array($lower, ['public/index.php', 'public/index.html', 'index.php', 'index.html', 'routes/web.php'], true)) {
                $entryPoints[] = $relative;
            }
            $frameworks = array_merge($frameworks, $this->frameworksFor($basename, $lower));
        }

        usort($files, static fn (array $left, array $right): int => strcmp($left['path'], $right['path']));

        $frameworks = array_values(array_unique($frameworks));
        $entryPoints = array_values(array_unique($entryPoints));
        sort($frameworks);
        sort($entryPoints);

        return [
            'files' => $files,
            'total_files' => count($files),
            'total_bytes' => $totalBytes,
            'frameworks' => $frameworks,
            'entry_points' => $entryPoints,
        ];
    }

    private function kind(string $extension): string
    {
        return match ($extension) {
            'php', 'php8', 'phtml' => 'php',
            'js', 'jsx', 'ts', 'tsx', 'vue' => 'javascript',
            'css', 'scss', 'sass', 'less' => 'style',
            'html', 'htm', 'blade.php' => 'markup',
            'py' => 'python',
            'json', 'yaml', 'yml', 'toml', 'xml' => 'config',
            default => 'other',
        };
    }

    /** @return list<string> */
    private function frameworksFor(string $basename, string $lower): array
    {
        $frameworks = [];
        if ($basename === 'artisan') {
            $frameworks[] = 'laravel';
        }
        if ($basename === 'manage.py') {
            $frameworks[] = 'django-or-python';
        }
        if ($basename === 'package.json') {
            $frameworks[] = 'node';
        }
        if ($basename === 'pyproject.toml') {
            $frameworks[] = 'python';
        }
        if ($basename === 'go.mod') {
            $frameworks[] = 'go';
        }
        if ($basename === 'cargo.toml') {
            $frameworks[] = 'rust';
        }
        if ($basename === 'composer.json' && ! in_array('laravel', $frameworks, true)) {
            $frameworks[] = 'php';
        }
        if ($lower === 'public/index.html' || $lower === 'index.html') {
            $frameworks[] = 'static-site';
        }

        return $frameworks;
    }
}
