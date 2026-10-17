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
# BackBox's required metasploit-framework comes from Rapid7's official bundled-package repository.
# Key and suite: github.com/rapid7/metasploit-omnibus/blob/25a202b4e6226631cb0f24716b2fff0136312805/config/templates/metasploit-framework-wrappers/msfupdate.erb
RUN curl --fail --show-error --location \
    https://apt.metasploit.com/metasploit-framework.gpg.key -o /tmp/metasploit-framework.asc \
    && test "$(gpg --show-keys --with-colons /tmp/metasploit-framework.asc | awk -F: '$1=="fpr" {print $10; exit}')" = 97B32012EA1176F053727A95C048F0B49DEEC457 \
    && gpg --batch --dearmor --output /usr/share/keyrings/metasploit-framework.gpg /tmp/metasploit-framework.asc \
    && printf '%s\n' 'deb [signed-by=/usr/share/keyrings/metasploit-framework.gpg] https://apt.metasploit.com lucid main' > /etc/apt/sources.list.d/metasploit-framework.list
RUN apt-get update && apt-get install --yes --install-recommends \
    -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold backbox-tools \
    && apt-get check && test -z "$(dpkg --audit)" \
    && mkdir -p /usr/local/share/flagship \
    && dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n' > /usr/local/share/flagship/package-inventory.tsv
LABEL io.github.mingusb.flagship.collection="backbox-tools"
# Ubuntu's chromium transitional packages skip their actual payload when snapd
# cannot run during a container build. Keep the full dependency graph and supply
# Canonical's matching browser/driver payload, using this Ubuntu base's libraries.
# Official Store metadata: https://api.snapcraft.io/v2/snaps/info/chromium
RUN apt-get install --yes --no-install-recommends squashfs-tools \
    && curl --fail --show-error --location \
       https://api.snapcraft.io/api/v1/snaps/download/XKEcBqPM06H1Z7zGOdG5fbICuf8NWK5R_3559.snap -o /tmp/chromium.snap \
    && python3 -c 'import hashlib; f=open("/tmp/chromium.snap","rb"); assert hashlib.file_digest(f,"sha3_384").hexdigest()=="216fd354bf39c175047d467dd0fc87c97c58395c9e156cd8bd221522a76742e63ac42c57700f9e90f67ebf729c6125e1"' \
    && mkdir -p /opt/flagship \
    && unsquashfs -no-progress -processors 4 -d /opt/flagship/chromium /tmp/chromium.snap \
    && rm /tmp/chromium.snap \
    && printf '#!/bin/sh\nexec /opt/flagship/chromium/usr/lib/chromium-browser/chrome "$@"\n' > /usr/local/bin/chromium \
    && printf '#!/bin/sh\nexec /opt/flagship/chromium/usr/lib/chromium-browser/chromedriver "$@"\n' > /usr/local/bin/chromedriver \
    && chmod 0755 /usr/local/bin/chromium /usr/local/bin/chromedriver \
    && dpkg-divert --local --rename --add /usr/bin/chromium-browser \
    && dpkg-divert --local --rename --add /usr/bin/chromedriver \
    && dpkg-divert --local --rename --add /usr/lib/chromium-browser/chromedriver \
    && ln -s /usr/local/bin/chromium /usr/bin/chromium-browser \
    && ln -s /usr/local/bin/chromium /usr/bin/chromium \
    && ln -s /usr/local/bin/chromedriver /usr/bin/chromedriver \
    && ln -s /usr/local/bin/chromedriver /usr/lib/chromium-browser/chromedriver \
    && ldd /opt/flagship/chromium/usr/lib/chromium-browser/chrome > /tmp/chromium-libraries \
    && ldd /opt/flagship/chromium/usr/lib/chromium-browser/chromedriver >> /tmp/chromium-libraries \
    && ! grep -q 'not found' /tmp/chromium-libraries \
    && chromium --version && chromedriver --version \
    && printf '%s\n' '{"publisher":"Canonical","snap":"chromium","revision":3559,"version":"155.0.8059.79","sha3_384":"216fd354bf39c175047d467dd0fc87c97c58395c9e156cd8bd221522a76742e63ac42c57700f9e90f67ebf729c6125e1","integration":"extracted payload with Ubuntu libraries; no sandbox-disabling flags"}' \
       > /usr/local/share/flagship/chromium-payload.json \
    && apt-get check && test -z "$(dpkg --audit)" \
    && dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n' > /usr/local/share/flagship/package-inventory.tsv
