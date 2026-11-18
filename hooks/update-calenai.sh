#!/bin/sh
set -eu

cd /var/www/html
# Serialize app updates when containers share the Nextcloud volume.
exec 9<apps
flock 9

installed=false
db_version=0
if [ -f config/config.php ]; then
    status=$(php occ status --output=json)
    installed=$(php -r 'echo json_decode($argv[1], true, 512, JSON_THROW_ON_ERROR)["installed"] ? "true" : "false";' "$status")
    if [ "$installed" = true ]; then
        db_version=$(php occ config:app:get calenai installed_version --default-value 0)
    fi
fi

php -r '
function appVersion($path) {
    $xml = simplexml_load_file($path);
    $version = trim((string) $xml->version);
    if ($version === "") {
        throw new RuntimeException("Missing CalenAI version in $path");
    }
    return $version;
}
$bundled = appVersion("/usr/src/nextcloud/apps/calenai/appinfo/info.xml");
$manifest = "apps/calenai/appinfo/info.xml";
$persisted = is_file($manifest) ? appVersion($manifest) : "0";
foreach ([$persisted, $argv[1]] as $version) {
    if (version_compare($version, $bundled, ">")) {
        fwrite(STDERR, "Refusing CalenAI downgrade from $version to $bundled.\n");
        exit(1);
    }
}' "$db_version"

rsync -rlc --delete /usr/src/nextcloud/apps/calenai/ apps/calenai/

# In pre-upgrade the upstream entrypoint runs occ upgrade immediately after this hook.
case "$0" in */pre-upgrade/*) exit 0 ;; esac

if [ "$installed" = true ]; then
    status=$(php occ status --output=json)
    upgrade=$(php -r 'echo json_decode($argv[1], true, 512, JSON_THROW_ON_ERROR)["needsDbUpgrade"] ? "true" : "false";' "$status")
    if [ "$upgrade" = true ]; then
        php occ upgrade --no-interaction
    fi
fi
