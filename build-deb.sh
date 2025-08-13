#!/bin/bash

PACKAGE_NAME="gpio-monitor"
VERSION="2.1.0"
ARCH="all"
MAINTAINER="Matteo Galvagni <galvagni.matteo@protonmail.com>"
DESCRIPTION="GPIO real-time monitoring server with SSE and REST API support"

BUILD_DIR="./build"
PACKAGE_DIR="${BUILD_DIR}/${PACKAGE_NAME}_${VERSION}_${ARCH}"

echo "Building ${PACKAGE_NAME} version ${VERSION}..."

# Clean build directory
rm -rf ${BUILD_DIR}
mkdir -p ${BUILD_DIR}

# Create package structure
mkdir -p ${PACKAGE_DIR}/DEBIAN
mkdir -p ${PACKAGE_DIR}/usr/lib/gpio-monitor/gpio_monitor
mkdir -p ${PACKAGE_DIR}/usr/lib/gpio-monitor/web
mkdir -p ${PACKAGE_DIR}/usr/bin
mkdir -p ${PACKAGE_DIR}/etc/gpio-monitor
mkdir -p ${PACKAGE_DIR}/lib/systemd/system
mkdir -p ${PACKAGE_DIR}/usr/share/doc/gpio-monitor

# Create control file
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

# Create postinst script
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
echo "GPIO Monitor installed successfully!"
echo ""
echo "COMMANDS:"
echo "  gpio-monitor help               - Show all commands"
echo ""
echo "ACCESS:"
echo "  Web interface: http://localhost:8787"
echo "  REST API documentation: /usr/share/doc/gpio-monitor/gpio-monitor-openapi.yaml"
echo ""

exit 0
EOF

# Create prerm script
cat > ${PACKAGE_DIR}/DEBIAN/prerm << 'EOF'
#!/bin/bash
set -e

systemctl stop gpio-monitor.service || true
systemctl disable gpio-monitor.service || true

exit 0
EOF

# Create postrm script
cat > ${PACKAGE_DIR}/DEBIAN/postrm << 'EOF'
#!/bin/bash
set -e

if [ "$1" = "purge" ]; then
    rm -rf /etc/gpio-monitor
fi

systemctl daemon-reload

exit 0
EOF

# Set permissions for DEBIAN scripts
chmod 755 ${PACKAGE_DIR}/DEBIAN/postinst
chmod 755 ${PACKAGE_DIR}/DEBIAN/prerm
chmod 755 ${PACKAGE_DIR}/DEBIAN/postrm

# Copy Python modules
cp -r gpio_monitor/* ${PACKAGE_DIR}/usr/lib/gpio-monitor/gpio_monitor/
chmod -R 755 ${PACKAGE_DIR}/usr/lib/gpio-monitor/gpio_monitor/

# Copy main script
cp gpio-monitor-main.py ${PACKAGE_DIR}/usr/lib/gpio-monitor/
chmod 755 ${PACKAGE_DIR}/usr/lib/gpio-monitor/gpio-monitor-main.py

# Copy web files
cp web/index.html ${PACKAGE_DIR}/usr/lib/gpio-monitor/web/
chmod 644 ${PACKAGE_DIR}/usr/lib/gpio-monitor/web/index.html

# Copy CLI script
cp gpio-monitor-cli.py ${PACKAGE_DIR}/usr/bin/gpio-monitor
chmod 755 ${PACKAGE_DIR}/usr/bin/gpio-monitor

# Copy systemd service
cp debian/gpio-monitor.service ${PACKAGE_DIR}/lib/systemd/system/
chmod 644 ${PACKAGE_DIR}/lib/systemd/system/gpio-monitor.service

# Create default config
echo '{"port": 8787, "monitored_pins": []}' > ${PACKAGE_DIR}/etc/gpio-monitor/config.json
chmod 644 ${PACKAGE_DIR}/etc/gpio-monitor/config.json

# Copy documentation
if [ -f README.md ]; then
    cp README.md ${PACKAGE_DIR}/usr/share/doc/gpio-monitor/
fi

if [ -f docs/gpio-monitor-openapi.yaml ]; then
    cp docs/gpio-monitor-openapi.yaml ${PACKAGE_DIR}/usr/share/doc/gpio-monitor/
    chmod 644 ${PACKAGE_DIR}/usr/share/doc/gpio-monitor/gpio-monitor-openapi.yaml
fi

# Create version file
echo "${VERSION}" > ${PACKAGE_DIR}/usr/share/doc/gpio-monitor/VERSION

# Build the package
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
else
    echo "Error: Package build failed"
    exit 1
fi