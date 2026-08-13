<?php

$root = dirname(__DIR__);
$required = [
    $root . '/index.php',
    $root . '/src/App.php',
];

foreach ($required as $file) {
    if (!is_file($file)) {
        fwrite(STDERR, "Missing fixture file: {$file}\n");
        exit(1);
    }
}

require $root . '/src/App.php';
$app = new App();
if ($app->message() !== 'Empy fixture is healthy') {
    fwrite(STDERR, "Unexpected fixture response\n");
    exit(1);
}

echo "fixture audit passed\n";
