FROM docker.io/parrotsec/security@sha256:2fe6606fed814618a6bc91a07f193a5b6aa9660b774fc319e6c8fd4b569e2f06
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 0755 /usr/sbin/policy-rc.d
RUN apt-get update && apt-get install --yes --install-recommends \
    -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold parrot-tools-full \
    && apt-get check && test -z "$(dpkg --audit)" \
    && mkdir -p /usr/local/share/flagship \
    && dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n' > /usr/local/share/flagship/package-inventory.tsv
LABEL io.github.mingusb.flagship.collection="parrot-tools-full"
