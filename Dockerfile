ARG NEXTCLOUD_VARIANT=fpm-alpine
FROM nextcloud:35-${NEXTCLOUD_VARIANT}
LABEL org.opencontainers.image.source="https://github.com/ajctrl/nextcloud-calenai"

ARG CALENAI_VERSION=1.2.7
ARG CALENAI_SHA256=2940055cfa18569ec2fd6175659601a93aa66eef14d48ec3aa5d1fa3fee90a4a
RUN curl -fsSL -o /tmp/calenai.tar.gz "https://github.com/ajctrl/CalenAI/releases/download/v${CALENAI_VERSION}/calenai-${CALENAI_VERSION}.tar.gz" \
    && echo "${CALENAI_SHA256}  /tmp/calenai.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/calenai.tar.gz -C /usr/src/nextcloud/apps \
    && php -r '$app = simplexml_load_file("/usr/src/nextcloud/apps/calenai/appinfo/info.xml"); \
        if ((string) $app->id !== "calenai" || trim((string) $app->version) !== $argv[1]) { \
            throw new RuntimeException("CalenAI manifest does not match release " . $argv[1]); \
        }' "$CALENAI_VERSION" \
    && rm /tmp/calenai.tar.gz \
    && printf '\n/apps/calenai/\n' >> /upgrade.exclude

COPY --chmod=755 hooks/update-calenai.sh /docker-entrypoint-hooks.d/before-starting/update-calenai.sh
# Core upgrades must sync the guarded app files before Nextcloud migrates its database.
RUN ln -s /docker-entrypoint-hooks.d/before-starting/update-calenai.sh /docker-entrypoint-hooks.d/pre-upgrade/update-calenai.sh
