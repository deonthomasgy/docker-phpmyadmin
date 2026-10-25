<?php
declare(strict_types=1);
define('ROOT_PATH', '/var/www/html/');
define('PHPMYADMIN', 1);
require ROOT_PATH . 'libraries/constants.php';
require AUTOLOAD_FILE;
$cfg = ['environment' => 'production'];
$containerBuilder = new Symfony\Component\DependencyInjection\ContainerBuilder();
$twig = PhpMyAdmin\Template::getTwigEnvironment(null);
$count = 0;
$files = new RecursiveIteratorIterator(new RecursiveDirectoryIterator(ROOT_PATH . 'templates'));
foreach ($files as $file) {
    if (!$file->isFile() || $file->getExtension() !== 'twig') {
        continue;
    }
    $name = substr($file->getPathname(), strlen(ROOT_PATH . 'templates/'));
    $twig->load($name);
    ++$count;
}
echo "Compiled $count phpMyAdmin templates with Twig " . Twig\Environment::VERSION . "\n";
