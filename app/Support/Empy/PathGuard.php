<?php

namespace App\Support\Empy;

use InvalidArgumentException;

final class PathGuard
{
    public function normalize(string $path): string
    {
        $path = str_replace('\\', '/', $path);

        if ($path === '' || str_contains($path, "\0") || str_starts_with($path, '/')
            || preg_match('/^[A-Za-z]:\//', $path) === 1) {
            throw new InvalidArgumentException('Archive path is absolute or invalid.');
        }

        $segments = [];
        foreach (explode('/', $path) as $segment) {
            if ($segment === '' || $segment === '.') {
                continue;
            }
            if ($segment === '..') {
                throw new InvalidArgumentException('Archive path traversal is not allowed.');
            }
            $segments[] = $segment;
        }

        if ($segments === []) {
            throw new InvalidArgumentException('Archive path is empty.');
        }

        return implode('/', $segments);
    }

    public function join(string $base, string $relative): string
    {
        return rtrim($base, DIRECTORY_SEPARATOR).DIRECTORY_SEPARATOR
            .str_replace('/', DIRECTORY_SEPARATOR, $this->normalize($relative));
    }

    public function isIgnored(string $relative): bool
    {
        $path = trim(str_replace('\\', '/', $relative), '/');
        if ($path === '') {
            return true;
        }

        $parts = explode('/', $path);
        foreach ($parts as $part) {
            if (in_array($part, ['.git', '.empy', 'node_modules', 'vendor'], true)) {
                return true;
            }
        }

        return str_starts_with($path, 'storage/framework/')
            || str_starts_with($path, 'storage/logs/');
    }
}
