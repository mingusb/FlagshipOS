FROM docker.io/kalilinux/kali-rolling@sha256:02f5d6c019e549b0f55da58e835cad5355ef1030c6b2645265a324e37dfc4acc
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 0755 /usr/sbin/policy-rc.d
# Use Kali's official CDN directly while retaining its signed repository metadata.
RUN sed -i 's|^URIs: http://http.kali.org/kali/$|URIs: http://kali.download/kali/|' /etc/apt/sources.list.d/kali.sources \
    && grep -qx 'URIs: http://kali.download/kali/' /etc/apt/sources.list.d/kali.sources
RUN apt-get update && apt-get install --yes --install-recommends \
    -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold kali-linux-everything \
    && apt-get check && test -z "$(dpkg --audit)" \
    && mkdir -p /usr/local/share/flagship \
    && dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n' > /usr/local/share/flagship/package-inventory.tsv
LABEL io.github.mingusb.flagship.collection="kali-linux-everything"
