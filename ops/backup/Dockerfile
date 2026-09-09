FROM alpine:3.24

# Base tags here are moving, not digest-pinned, so a rebuild normally picks up
# Alpine's security fixes on its own. What it cannot pick up is a fix published
# *after* the base image was last rebuilt: the package sits installed at the old
# version while the repository already carries the patch, and the image scan —
# rightly — fails the build on it. That is exactly what 3.24 arrived with:
# openssl 3.5.7-r0 against CVE-2026-14456, fixed in 3.5.8-r0 and already in the
# 3.24 repository. Upgrading first closes that window at build time instead of
# waiting on a base rebuild.
RUN apk upgrade --no-cache \
    && apk add --no-cache \
        bash \
        busybox-extras \
        ca-certificates \
        coreutils \
        findutils \
        postgresql16-client \
        rclone \
        tar \
        tzdata \
        util-linux

COPY crontab /etc/crontabs/root
COPY bin/ /opt/backup/bin/
RUN chmod 0755 /opt/backup/bin/* \
    && mkdir -p /backups/base /backups/dumps /backups/remote /config/rclone

ENV RCLONE_CONFIG=/config/rclone/rclone.conf
ENTRYPOINT ["/opt/backup/bin/entrypoint"]
CMD ["crond", "-f", "-l", "2"]
