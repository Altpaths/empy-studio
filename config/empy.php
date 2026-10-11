<?php

return [
    'max_archive_bytes' => (int) env('EMPY_MAX_ARCHIVE_BYTES', 100 * 1024 * 1024),
    'max_file_bytes' => (int) env('EMPY_MAX_FILE_BYTES', 25 * 1024 * 1024),
    'provider_order' => array_values(array_filter(array_map(
        static fn (string $provider): string => trim($provider),
        explode(',', (string) env('EMPY_PROVIDER_ORDER', 'ollama,openai_compatible')),
    ))),
    'provider_timeout' => (int) env('EMPY_PROVIDER_TIMEOUT', 120),
    'ollama' => [
        'base_url' => rtrim((string) env('EMPY_OLLAMA_BASE_URL', 'http://127.0.0.1:11434'), '/'),
        'model' => (string) env('EMPY_OLLAMA_MODEL', ''),
    ],
    'openai_compatible' => [
        'base_url' => rtrim((string) env('EMPY_OPENAI_BASE_URL', ''), '/'),
        'api_key' => (string) env('EMPY_OPENAI_API_KEY', ''),
        'model' => (string) env('EMPY_OPENAI_MODEL', ''),
    ],
];
