#!/usr/bin/php
<?PHP
$docroot = '/usr/local/emhttp';
$_SERVER['DOCUMENT_ROOT'] = $docroot;
require_once("$docroot/plugins/dynamix.docker.manager/include/DockerClient.php");
$name = 'Nomad';
$DockerClient = new DockerClient();
$DockerTemplates = new DockerTemplates();
$_GET['updateContainer'] = true;
$_GET['ct'] = array($name);
include("$docroot/plugins/dynamix.docker.manager/include/CreateDocker.php");
exec("docker start " . escapeshellarg($name));
