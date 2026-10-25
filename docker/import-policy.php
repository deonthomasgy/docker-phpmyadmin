<?php
declare(strict_types=1);

// The import classes are also removed from the image and generated autoloader.
// Reject crafted requests before phpMyAdmin reads uploaded/import-directory data.
// Export uses the separate "what" parameter, so XML/ODS exports remain available.
$importFormat = $_POST['format'] ?? null;
if (is_string($importFormat) && in_array(strtolower($importFormat), ['xml', 'ods'], true)) {
    http_response_code(403);
    header('Content-Type: text/plain; charset=UTF-8');
    echo 'XML and ODS imports are disabled by the container security policy.';
    exit;
}
unset($importFormat);
