FROM docker.io/library/ubuntu@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
USER root
ENV DEBIAN_FRONTEND=noninteractive CHECKPOINT_DISABLE=1
RUN test "$(dpkg --print-architecture)" = amd64 \
    && printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 0755 /usr/sbin/policy-rc.d
# Reuse the pinned base's UID 1000 so Distrobox's default mapped user can read SIFT's original home.
RUN apt-get update && apt-get install --yes --no-install-recommends ca-certificates curl sudo gnupg \
    && test "$(id -u ubuntu)" = 1000 && test "$(id -g ubuntu)" = 1000 \
    && usermod --login sift --home /home/sift --move-home ubuntu \
    && groupmod --new-name sift ubuntu
RUN curl --fail --show-error --location \
    https://github.com/ekristen/cast/releases/download/v1.0.42/cast-v1.0.42-linux-amd64.deb -o /tmp/cast.deb \
    && printf '%s\n' '9775d46a42f77030407cd3ba37d5f32334d50e0d4b021ece113c23cbea2c7573  /tmp/cast.deb' | sha256sum --check \
    && apt-get install --yes /tmp/cast.deb
# Cast config path: github.com/ekristen/cast/blob/v1.0.42/pkg/installer/installer.go
# Salt reads minion.d/*.conf and local pillar_roots:
# docs.saltproject.io/en/latest/ref/configuration/minion.html
# Preserve this build's hostname so upstream sift.config.hostname needs no extra capability.
# Defer service activation during installation: github.com/systemd/systemd/blob/v255/docs/ENVIRONMENT.md
RUN mkdir -p /var/cache/cast/installer/salt/minion.d /var/cache/flagship/pillar \
    && printf '%s\n' 'pillar_roots:' '  base:' '    - /var/cache/flagship/pillar' \
        > /var/cache/cast/installer/salt/minion.d/flagship.conf \
    && printf '%s\n' 'base:' '  "*":' '    - flagship' > /var/cache/flagship/pillar/top.sls \
    && printf '%s\n' "sift_hostname: {{ grains['nodename'] | tojson }}" > /var/cache/flagship/pillar/flagship.sls \
    && SYSTEMD_OFFLINE=1 cast install --user sift --mode desktop teamdfir/sift-saltstack@v2026.04.21 \
    && rm -f /var/cache/cast/installer/salt/minion.d/flagship.conf \
        /var/cache/flagship/pillar/top.sls /var/cache/flagship/pillar/flagship.sls \
    && rmdir /var/cache/flagship/pillar /var/cache/flagship \
    && apt-get check && test -z "$(dpkg --audit)" \
    && mkdir -p /usr/local/share/flagship \
    && dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n' > /usr/local/share/flagship/package-inventory.tsv
LABEL io.github.mingusb.flagship.collection="sift-desktop-v2026.04.21"
