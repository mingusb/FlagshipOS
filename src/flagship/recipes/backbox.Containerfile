FROM docker.io/library/ubuntu@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN test "$(. /etc/os-release && printf '%s' "$VERSION_ID")" = 24.04 \
    && printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 0755 /usr/sbin/policy-rc.d
RUN apt-get update && apt-get install --yes --no-install-recommends ca-certificates curl gnupg
# Fingerprint is published by the official BackBox nine Launchpad archive.
RUN curl --fail --show-error --location \
    'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xF10FF8AFAF205A39312C0A20F2B4C9A44882013D' -o /tmp/backbox.asc \
    && test "$(gpg --show-keys --with-colons /tmp/backbox.asc | awk -F: '$1=="fpr" {print $10; exit}')" = F10FF8AFAF205A39312C0A20F2B4C9A44882013D \
    && gpg --batch --dearmor --output /usr/share/keyrings/backbox-nine.gpg /tmp/backbox.asc \
    && printf '%s\n' 'deb [signed-by=/usr/share/keyrings/backbox-nine.gpg] https://ppa.launchpadcontent.net/backbox/nine/ubuntu noble main' > /etc/apt/sources.list.d/backbox-nine.list
RUN apt-get update && apt-get install --yes --install-recommends \
    -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold backbox-tools \
    && apt-get check && test -z "$(dpkg --audit)" \
    && mkdir -p /usr/local/share/flagship \
    && dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n' > /usr/local/share/flagship/package-inventory.tsv
LABEL io.github.mingusb.flagship.collection="backbox-tools"
