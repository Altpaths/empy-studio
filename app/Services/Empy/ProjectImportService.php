<?php

namespace App\Services\Empy;

use App\Models\Project;
use App\Support\Empy\PathGuard;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Storage;
use RuntimeException;
use ZipArchive;

final class ProjectImportService
{
    public function __construct(
        private readonly PathGuard $paths,
        private readonly ProjectIndexer $indexer,
    ) {}

    public function import(UploadedFile|string $archive, ?string $name = null): Project
    {
        $archivePath = $archive instanceof UploadedFile ? $archive->getRealPath() : $archive;
        if (! is_string($archivePath) || ! is_file($archivePath)) {
            throw new RuntimeException('Project archive could not be read.');
        }

        $project = Project::create([
            'name' => $name ?: pathinfo($archivePath, PATHINFO_FILENAME),
            'original_filename' => $archive instanceof UploadedFile ? $archive->getClientOriginalName() : basename($archivePath),
            'source_path' => 'empy/projects/pending',
            'status' => 'importing',
        ]);
        $sourcePath = 'empy/projects/'.$project->id.'/source';
        $destination = Storage::disk('local')->path($sourcePath);

        try {
            $this->extract($archivePath, $destination);
            $manifest = $this->indexer->index($destination);
            $project->update([
                'source_path' => $sourcePath,
                'manifest' => $manifest,
                'detected_stack' => [
                    'frameworks' => $manifest['frameworks'],
                    'entry_points' => $manifest['entry_points'],
                ],
                'status' => 'ready',
            ]);
        } catch (\Throwable $exception) {
            Storage::disk('local')->deleteDirectory('empy/projects/'.$project->id);
            $project->delete();
            throw $exception;
        }

        return $project->fresh();
    }

    private function extract(string $archivePath, string $destination): void
    {
        $zip = new ZipArchive;
        $result = $zip->open($archivePath);
        if ($result !== true) {
            throw new RuntimeException('Project archive is not a readable ZIP.');
        }

        $maxArchiveBytes = (int) config('empy.max_archive_bytes');
        $maxFileBytes = (int) config('empy.max_file_bytes');
        $totalBytes = 0;
        $created = [];
        try {
            for ($index = 0; $index < $zip->numFiles; $index++) {
                $stat = $zip->statIndex($index);
                $entryName = (string) ($stat['name'] ?? '');
                if ($entryName === '' || str_ends_with($entryName, '/')) {
                    continue;
                }
                $relative = $this->paths->normalize($entryName);
                $size = (int) ($stat['size'] ?? 0);
                if ($size > $maxFileBytes || ($totalBytes + $size) > $maxArchiveBytes) {
                    throw new RuntimeException('Project archive is larger than the configured import safety limit.');
                }

                $opsys = 0;
                $externalAttributes = 0;
                if ($zip->getExternalAttributesIndex($index, $opsys, $externalAttributes)
                    && $opsys === ZipArchive::OPSYS_UNIX
                    && (($externalAttributes >> 16) & 0xF000) === 0xA000) {
                    throw new RuntimeException('Symbolic links are not allowed in a project archive.');
                }

                $target = $this->paths->join($destination, $relative);
                $parent = dirname($target);
                if (! is_dir($parent) && ! mkdir($parent, 0750, true) && ! is_dir($parent)) {
                    throw new RuntimeException('Project workspace could not be created.');
                }
                $stream = $zip->getStream($entryName);
                if ($stream === false) {
                    throw new RuntimeException('A project archive entry could not be read.');
                }
                $output = fopen($target, 'wb');
                if ($output === false) {
                    fclose($stream);
                    throw new RuntimeException('A project file could not be written.');
                }
                stream_copy_to_stream($stream, $output);
                fclose($output);
                fclose($stream);
                chmod($target, 0640);
                $created[] = $target;
                $totalBytes += $size;
            }
        } finally {
            $zip->close();
        }

        if ($created === []) {
            throw new RuntimeException('Project archive contains no usable files.');
        }
    }
}
