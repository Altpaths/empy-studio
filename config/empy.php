<?php

return [
    'version' => (string) env('EMPY_VERSION', '1.0.0'),
    'max_archive_bytes' => (int) env('EMPY_MAX_ARCHIVE_BYTES', 100 * 1024 * 1024),
    'max_file_bytes' => (int) env('EMPY_MAX_FILE_BYTES', 25 * 1024 * 1024),
    // Empty means the archive can be extracted directly into a DirectAdmin
    // public_html directory. Set a prefix only when a nested project folder
    // is intentionally required by the deployment target.
    'delivery_prefix' => trim((string) env('EMPY_DELIVERY_PREFIX', '')),
    'delivery_strip_root' => filter_var(env('EMPY_DELIVERY_STRIP_ROOT', true), FILTER_VALIDATE_BOOL),
    'provider_order' => array_values(array_filter(array_map(
        static fn (string $provider): string => trim($provider),
        explode(',', (string) env('EMPY_PROVIDER_ORDER', 'codex,gemini,ollama,openai_compatible')),
    ))),
    'provider_timeout' => (int) env('EMPY_PROVIDER_TIMEOUT', 120),
    'codex' => [
        'enabled' => filter_var(env('EMPY_CODEX_ENABLED', true), FILTER_VALIDATE_BOOL),
        'binary' => (string) env('EMPY_CODEX_BIN', 'codex'),
        'model' => (string) env('EMPY_CODEX_MODEL', ''),
        'timeout' => (int) env('EMPY_CODEX_TIMEOUT', 300),
    ],
    'ollama' => [
        'base_url' => rtrim((string) env('EMPY_OLLAMA_BASE_URL', 'http://127.0.0.1:11434'), '/'),
        'model' => (string) env('EMPY_OLLAMA_MODEL', ''),
    ],
    'gemini' => [
        'base_url' => rtrim((string) env('EMPY_GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta'), '/'),
        'api_key' => (string) env('EMPY_GEMINI_API_KEY', ''),
        'model' => (string) env('EMPY_GEMINI_MODEL', ''),
    ],
    'openai_compatible' => [
        'base_url' => rtrim((string) env('EMPY_OPENAI_BASE_URL', ''), '/'),
        'api_key' => (string) env('EMPY_OPENAI_API_KEY', ''),
        'model' => (string) env('EMPY_OPENAI_MODEL', ''),
    ],
];
