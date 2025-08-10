#!/bin/bash

PACKAGE_NAME="gpio-monitor"
VERSION="1.0.0"
ARCH="all"
MAINTAINER="Your Name <your.email@example.com>"
DESCRIPTION="GPIO real-time monitoring server with SSE support"

BUILD_DIR="./build"
PACKAGE_DIR="${BUILD_DIR}/${PACKAGE_NAME}_${VERSION}_${ARCH}"

echo "Building ${PACKAGE_NAME} version ${VERSION}..."

rm -rf ${BUILD_DIR}
mkdir -p ${BUILD_DIR}

mkdir -p ${PACKAGE_DIR}/DEBIAN
mkdir -p ${PACKAGE_DIR}/usr/lib/gpio-monitor
mkdir -p ${PACKAGE_DIR}/usr/bin
mkdir -p ${PACKAGE_DIR}/etc/gpio-monitor
mkdir -p ${PACKAGE_DIR}/lib/systemd/system

cat > ${PACKAGE_DIR}/DEBIAN/control << EOF
Package: ${PACKAGE_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: ${MAINTAINER}
Description: ${DESCRIPTION}
 GPIO Monitor provides a real-time web interface for monitoring
 Raspberry Pi GPIO pin states using Server-Sent Events (SSE).
 Features include automatic state change detection, web dashboard,
 and RESTful event streaming.
Depends: python3 (>= 3.7), systemd
EOF

cat > ${PACKAGE_DIR}/DEBIAN/postinst << 'EOF'
#!/bin/bash
set -e

if [ ! -f /etc/gpio-monitor/config.json ]; then
    echo '{"port": 8787, "monitored_pins": []}' > /etc/gpio-monitor/config.json
fi

systemctl daemon-reload
systemctl enable gpio-monitor.service
systemctl start gpio-monitor.service

echo "GPIO Monitor installed successfully!"
echo ""
echo "Quick Start:"
echo "  1. Add pins to monitor: sudo gpio-monitor add-pin 17"
echo "  2. Add more pins: sudo gpio-monitor add-pin 27"
echo "  3. View status: gpio-monitor status"
echo "  4. Access web UI: http://localhost:8787"
echo ""
echo "Use 'gpio-monitor help' for all commands"

exit 0
EOF

cat > ${PACKAGE_DIR}/DEBIAN/prerm << 'EOF'
#!/bin/bash
set -e

systemctl stop gpio-monitor.service || true
systemctl disable gpio-monitor.service || true

exit 0
EOF

cat > ${PACKAGE_DIR}/DEBIAN/postrm << 'EOF'
#!/bin/bash
set -e

if [ "$1" = "purge" ]; then
    rm -rf /etc/gpio-monitor
fi

systemctl daemon-reload

exit 0
EOF

chmod 755 ${PACKAGE_DIR}/DEBIAN/postinst
chmod 755 ${PACKAGE_DIR}/DEBIAN/prerm
chmod 755 ${PACKAGE_DIR}/DEBIAN/postrm

cp gpio-monitor.py ${PACKAGE_DIR}/usr/lib/gpio-monitor/
chmod 755 ${PACKAGE_DIR}/usr/lib/gpio-monitor/gpio-monitor.py

cp gpio-monitor-cli.py ${PACKAGE_DIR}/usr/bin/gpio-monitor
chmod 755 ${PACKAGE_DIR}/usr/bin/gpio-monitor

cp gpio-monitor.service ${PACKAGE_DIR}/lib/systemd/system/
chmod 644 ${PACKAGE_DIR}/lib/systemd/system/gpio-monitor.service

echo '{"port": 8787, "monitored_pins": []}' > ${PACKAGE_DIR}/etc/gpio-monitor/config.json
chmod 644 ${PACKAGE_DIR}/etc/gpio-monitor/config.json

dpkg-deb --build ${PACKAGE_DIR}

if [ $? -eq 0 ]; then
    echo ""
    echo "Package built successfully: ${BUILD_DIR}/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
    echo ""
    echo "To install:"
    echo "  sudo dpkg -i ${BUILD_DIR}/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
    echo ""
    echo "To uninstall:"
    echo "  sudo dpkg -r ${PACKAGE_NAME}"
    echo ""
    echo "To completely remove (including config):"
    echo "  sudo dpkg --purge ${PACKAGE_NAME}"
else
    echo "Error: Package build failed"
    exit 1
fi