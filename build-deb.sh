#!/bin/bash

PACKAGE_NAME="gpio-monitor"
VERSION="2.0.0"
ARCH="all"
MAINTAINER="Matteo Galvagni <galvagni.matteo@protonmail.com>"
DESCRIPTION="GPIO real-time monitoring server with SSE and REST API support"

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
mkdir -p ${PACKAGE_DIR}/usr/share/doc/gpio-monitor

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
 RESTful API for dynamic pin management, and no-restart configuration updates.
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

echo ""
echo "GPIO Monitor v2.0 installed successfully!"
echo ""
echo "COMMANDS:"
echo "  gpio-monitor add-pin <pin>      - Add GPIO pin to monitoring"
echo "  gpio-monitor remove-pin <pin>   - Remove GPIO pin"
echo "  gpio-monitor list-pins          - List all pins"
echo "  gpio-monitor set-pull <pin> <mode>     - Set pull resistor (up/down/none)"
echo "  gpio-monitor set-debounce <pin> <level> - Set debouncing (LOW/MEDIUM/HIGH)"
echo "  gpio-monitor status             - Show current status"
echo "  gpio-monitor help               - Show all commands"
echo ""
echo "ACCESS:"
echo "  Web interface: http://localhost:8787"
echo "  REST API documentation: /usr/share/doc/gpio-monitor/gpio-monitor-openapi.yaml"
echo ""

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

cp index.html ${PACKAGE_DIR}/usr/lib/gpio-monitor/
chmod 755 ${PACKAGE_DIR}/usr/lib/gpio-monitor/index.html

cp gpio-monitor-cli.py ${PACKAGE_DIR}/usr/bin/gpio-monitor
chmod 755 ${PACKAGE_DIR}/usr/bin/gpio-monitor

cp gpio-monitor.service ${PACKAGE_DIR}/lib/systemd/system/
chmod 644 ${PACKAGE_DIR}/lib/systemd/system/gpio-monitor.service

echo '{"port": 8787, "monitored_pins": []}' > ${PACKAGE_DIR}/etc/gpio-monitor/config.json
chmod 644 ${PACKAGE_DIR}/etc/gpio-monitor/config.json

# Copy documentation
if [ -f README.md ]; then
    cp README.md ${PACKAGE_DIR}/usr/share/doc/gpio-monitor/
fi

if [ -f gpio-monitor-openapi.yaml ]; then
    cp gpio-monitor-openapi.yaml ${PACKAGE_DIR}/usr/share/doc/gpio-monitor/
    chmod 644 ${PACKAGE_DIR}/usr/share/doc/gpio-monitor/gpio-monitor-openapi.yaml
fi

# Create a version file
echo "${VERSION}" > ${PACKAGE_DIR}/usr/share/doc/gpio-monitor/VERSION

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