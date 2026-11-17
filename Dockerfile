FROM nextcloud:35-fpm-alpine

ADD --checksum=sha256:2940055cfa18569ec2fd6175659601a93aa66eef14d48ec3aa5d1fa3fee90a4a https://github.com/ajctrl/CalenAI/releases/download/v1.2.7/calenai-1.2.7.tar.gz /tmp/calenai.tar.gz
RUN tar -xzf /tmp/calenai.tar.gz -C /usr/src/nextcloud/apps \
    && test -s /usr/src/nextcloud/apps/calenai/appinfo/info.xml \
    && rm /tmp/calenai.tar.gz
