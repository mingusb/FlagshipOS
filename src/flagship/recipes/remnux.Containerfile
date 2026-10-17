FROM docker.io/remnux/remnux-distro@sha256:880089abf02feb5240607545ab601e2d97d7b1c213d6341aa2e7ce356f65c8c2
USER root
ENV DEBIAN_FRONTEND=noninteractive CHECKPOINT_DISABLE=1
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 0755 /usr/sbin/policy-rc.d
# This is the upstream documented expansion of its container to a full install.
# Defer service activation during installation: github.com/systemd/systemd/blob/v255/docs/ENVIRONMENT.md
RUN curl --fail --show-error --location \
    https://raw.githubusercontent.com/REMnux/distro/master/files/remnux-installer.sh -o /tmp/remnux-installer \
    && printf '%s\n' 'c1e2dbc7191c4c3382deea2c5ecc40d729c271b7d6b8897caa5cbeb7e3e7d203  /tmp/remnux-installer' | sha256sum --check \
    && SYSTEMD_OFFLINE=1 bash /tmp/remnux-installer install --user remnux --mode dedicated --version v2026.42.3 \
    && apt-get check && test -z "$(dpkg --audit)" \
    && mkdir -p /usr/local/share/flagship \
    && dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n' > /usr/local/share/flagship/package-inventory.tsv
LABEL io.github.mingusb.flagship.collection="remnux-dedicated-v2026.42.3"
