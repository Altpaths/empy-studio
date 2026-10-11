<?php

namespace App\Services\Empy;

use App\Exceptions\EmpyVerificationException;
use App\Models\Artifact;
use App\Models\Ticket;
use App\Support\Empy\PathGuard;
use FilesystemIterator;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use ZipArchive;

final class DeliveryService
{
    public function __construct(private readonly PathGuard $paths) {}

    public function deliver(Ticket $ticket): Artifact
    {
        if ($ticket->status !== 'verified') {
            throw new EmpyVerificationException('A verified ticket is required before ZIP delivery.', 'verification_required');
        }
        $project = $ticket->project;
        $root = Storage::disk($project->source_disk)->path($project->source_path);
        $deliveryPath = 'empy/deliveries/'.$ticket->id.'/'.Str::slug($project->name).'.zip';
        $absoluteZip = Storage::disk('local')->path($deliveryPath);
        $parent = dirname($absoluteZip);
        if (! is_dir($parent) && ! mkdir($parent, 0750, true) && ! is_dir($parent)) {
            throw new EmpyVerificationException('Delivery directory could not be created.', 'delivery_failed');
        }
        $zip = new ZipArchive;
        if ($zip->open($absoluteZip, ZipArchive::CREATE | ZipArchive::OVERWRITE) !== true) {
            throw new EmpyVerificationException('Delivery ZIP could not be opened.', 'delivery_failed');
        }
        $configuredPrefix = trim((string) config('empy.delivery_prefix', ''));
        $prefix = $configuredPrefix === '' ? '' : $this->paths->normalize($configuredPrefix);
        $sourceRoot = filter_var(config('empy.delivery_strip_root', true), FILTER_VALIDATE_BOOL)
            ? $this->singleWrapperPrefix($root)
            : null;
        $manifest = [];
        try {
            $iterator = new RecursiveIteratorIterator(
                new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS),
            );
            foreach ($iterator as $file) {
                if (! $file->isFile() || $file->isLink()) {
                    continue;
                }
                $relative = ltrim(str_replace('\\', '/', substr($file->getPathname(), strlen($root))), '/');
                if ($this->excluded($relative)) {
                    continue;
                }
                if ($sourceRoot !== null) {
                    $relative = substr($relative, strlen($sourceRoot) + 1);
                }
                $safe = $this->paths->normalize($relative);
                $zipPath = $prefix === '' ? $safe : $prefix.'/'.$safe;
                if (! $zip->addFile($file->getPathname(), $zipPath)) {
                    throw new EmpyVerificationException("Could not add {$safe} to delivery ZIP.", 'delivery_failed');
                }
                $manifest[] = ['path' => $safe, 'sha256' => hash_file('sha256', $file->getPathname()), 'size' => $file->getSize()];
            }
            sort($manifest);
            $manifestPath = $prefix === '' ? 'EMPy-MANIFEST.json' : $prefix.'/EMPy-MANIFEST.json';
            $zip->addFromString($manifestPath, json_encode([
                'project' => $project->name,
                'ticket_id' => $ticket->id,
                'files' => $manifest,
                'generated_at' => now()->toIso8601String(),
            ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR));
        } finally {
            $zip->close();
        }

        $check = new ZipArchive;
        if ($check->open($absoluteZip) !== true || $check->numFiles === 0) {
            throw new EmpyVerificationException('Delivery ZIP failed its archive smoke test.', 'delivery_invalid_zip');
        }
        for ($index = 0; $index < $check->numFiles; $index++) {
            $name = (string) $check->getNameIndex($index);
            if (str_contains(str_replace('\\', '/', $name), '../') || str_starts_with($name, '/')) {
                $check->close();
                throw new EmpyVerificationException('Delivery ZIP contains an unsafe path.', 'delivery_unsafe_path');
            }
        }
        $check->close();

        $artifact = Artifact::create([
            'ticket_id' => $ticket->id,
            'disk' => 'local',
            'path' => $deliveryPath,
            'sha256' => hash_file('sha256', $absoluteZip),
            'size' => filesize($absoluteZip) ?: 0,
            'manifest' => ['root' => $prefix === '' ? '.' : $prefix, 'files' => $manifest],
        ]);
        $ticket->update(['status' => 'delivered', 'result' => array_merge($ticket->result ?? [], ['artifact_id' => $artifact->id])]);

        return $artifact;
    }

    private function excluded(string $relative): bool
    {
        $normalized = trim(str_replace('\\', '/', $relative), '/');
        $parts = explode('/', $normalized);
        if (in_array('.git', $parts, true) || in_array('.empy', $parts, true)) {
            return true;
        }
        $basename = basename($normalized);

        return $basename === '.env' || str_starts_with($basename, '.env.')
            || str_starts_with($normalized, 'storage/logs/');
    }

    private function singleWrapperPrefix(string $root): ?string
    {
        $topLevel = [];
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS),
        );
        foreach ($iterator as $file) {
            if (! $file->isFile() || $file->isLink()) {
                continue;
            }
            $relative = ltrim(str_replace('\\', '/', substr($file->getPathname(), strlen($root))), '/');
            if ($this->excluded($relative)) {
                continue;
            }
            $parts = explode('/', $relative, 2);
            $topLevel[$parts[0]] = true;
        }
        if (count($topLevel) !== 1) {
            return null;
        }

        $prefix = array_key_first($topLevel);
        if (! is_string($prefix) || in_array(strtolower($prefix), [
            'app', 'bootstrap', 'config', 'database', 'dist', 'node_modules',
            'public', 'public_html', 'resources', 'routes', 'src', 'storage',
            'tests', 'vendor',
        ], true)) {
            return null;
        }

        return $prefix;
    }
}
