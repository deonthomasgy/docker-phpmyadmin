<?php
declare(strict_types=1);
define('ROOT_PATH', '/var/www/html/');
define('TEST_PATH', '/var/www/html/');
define('PHPMYADMIN', 1);
define('TESTSUITE', 1);
require '/var/www/html/test/bootstrap-dist.php';
spl_autoload_register(static function (string $class): void {
    $prefix = 'PhpMyAdmin\\Tests\\';
    if (str_starts_with($class, $prefix)) {
        $file = '/var/www/html/test/classes/' . str_replace('\\', '/', substr($class, strlen($prefix))) . '.php';
        if (is_file($file)) {
            require $file;
        }
    }
});
