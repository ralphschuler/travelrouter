SHELL := /bin/sh

PYTHON ?= python3
TARGET ?= generic-x86_64
IMAGE ?= dist/travelrouter-cm5-aarch64.img.gz
RESULTS_DIR ?= build/recovery-results
SCRATCH_DIR ?= build/recovery-vm
DIST ?= dist
KERNEL_RELEASE ?= 6.18.58-0-rpi
KERNEL_PACKAGE_VERSION ?= 6.18.58-r0
KERNEL_DEV_PACKAGE ?= linux-rpi-dev
ALPINE_BRANCH ?= v3.24
APK_ARCH ?= aarch64
KERNEL_PACKAGE_URL ?=
ARCH ?= arm64
CROSS_COMPILE ?=
DRIVER_REVISION ?= $(shell tr -d '\n' < image/drivers/rtl8192su/UPSTREAM_REVISION)
RTL8191SU ?= 1
DRIVER_BUILD_DIR ?= $(CURDIR)/build/rtl8192su
DRIVER_OUTPUT ?= $(DRIVER_BUILD_DIR)/r92su.ko

.PHONY: help lint unit audit check-build-options quality image-cm5 image-generic driver developer-ssh recovery-test-image \
	e2e-cm5 e2e-generic e2e-recovery site sign-update release-manifest verify-release-artifacts

help:
	@printf '%s\n' \
	  'TravelRouter build targets:' \
	  '  make lint unit audit quality' \
	  '  make image-cm5 [RTL8191SU=0] (driver included by default; 0 opts out)' \
	  '  make image-generic TARGET=generic-x86_64|generic-aarch64' \
	  '  make driver [KERNEL_RELEASE=... KERNEL_PACKAGE_VERSION=... DRIVER_REVISION=...]' \
	  '  make e2e-cm5 IMAGE=path/to/image.img.gz' \
	  '  make e2e-generic TARGET=generic-x86_64|generic-aarch64' \
	  '  make e2e-recovery IMAGE=path/to/image.img.gz'

lint:
	ruff check src tests image site
	bandit -q -r src image site -c pyproject.toml
	$(PYTHON) site/build.py
	$(PYTHON) site/check.py
	shellcheck -s sh image/*.sh image/e2e/*.sh image/targets/*.sh \
	  rootfs/etc/init.d/travelrouter rootfs/etc/init.d/travelrouter-bootstrap \
	  rootfs/etc/init.d/travelrouter-recovery rootfs/etc/init.d/travelrouter-ssh \
	  rootfs/etc/init.d/travelrouter-wifi \
	  rootfs/etc/travelrouter/recovery.sh

unit:
	PYTHONPATH=src coverage run --source=src/travelrouter -m unittest discover -s tests -v
	coverage report

audit:
	pip-audit -r requirements-dev.txt

check-build-options:
	@default="$$( $(MAKE) --no-print-directory -n image-cm5 )"; \
	 optout="$$( $(MAKE) --no-print-directory -n image-cm5 RTL8191SU=0 )"; \
	 printf '%s\n' "$$default" | grep -F 'RTL8191SU="1"' >/dev/null || \
	   { echo 'CM5 builds must include RTL8191SU by default' >&2; exit 1; }; \
	 printf '%s\n' "$$optout" | grep -F 'RTL8191SU="0"' >/dev/null || \
	   { echo 'RTL8191SU=0 must opt out of the driver' >&2; exit 1; }; \
	 echo 'Build option defaults and opt-out verified'

quality: lint unit audit check-build-options

image-cm5:
	KERNEL_RELEASE="$(KERNEL_RELEASE)" KERNEL_PACKAGE_VERSION="$(KERNEL_PACKAGE_VERSION)" \
	  KERNEL_DEV_PACKAGE="$(KERNEL_DEV_PACKAGE)" ALPINE_BRANCH="$(ALPINE_BRANCH)" \
	  APK_ARCH="$(APK_ARCH)" KERNEL_PACKAGE_URL="$(KERNEL_PACKAGE_URL)" \
	  ARCH="$(ARCH)" CROSS_COMPILE="$(CROSS_COMPILE)" \
	  DRIVER_REVISION="$(DRIVER_REVISION)" RTL8191SU="$(RTL8191SU)" sh image/build.sh

image-generic:
	sh image/build-generic.sh "$(TARGET)"

developer-ssh:
	docker build -f image/e2e/developer.Dockerfile -t travelrouter-ssh-test .
	docker run --rm --init --network none -e TRAVELROUTER_TEST_CONTAINER=yes \
	  -v "$(CURDIR):/source:ro" travelrouter-ssh-test sh /source/image/e2e/developer.sh

recovery-test-image:
	docker build -f image/e2e/recovery.Dockerfile -t travelrouter-recovery-test .

driver:
	$(MAKE) -C image/drivers/rtl8192su build \
	  SOURCE_ROOT="$(CURDIR)" BUILD_DIR="$(DRIVER_BUILD_DIR)" \
	  OUTPUT_MODULE="$(DRIVER_OUTPUT)" KERNEL_RELEASE="$(KERNEL_RELEASE)" \
	  KERNEL_PACKAGE_VERSION="$(KERNEL_PACKAGE_VERSION)" \
	  KERNEL_DEV_PACKAGE="$(KERNEL_DEV_PACKAGE)" ALPINE_BRANCH="$(ALPINE_BRANCH)" \
	  APK_ARCH="$(APK_ARCH)" KERNEL_PACKAGE_URL="$(KERNEL_PACKAGE_URL)" \
	  DRIVER_REVISION="$(DRIVER_REVISION)"

e2e-cm5:
	sh image/e2e/run.sh "$(IMAGE)"

e2e-generic:
	sh image/e2e/generic.sh "$(TARGET)"

e2e-recovery:
	$(PYTHON) image/e2e/run.py --image "$(IMAGE)" --output "$(RESULTS_DIR)" \
	  --scratch "$(SCRATCH_DIR)" --recovery

site:
	$(PYTHON) site/build.py
	$(PYTHON) site/check.py

sign-update:
	$(PYTHON) image/sign_update.py

release-manifest:
	$(PYTHON) image/release_manifest.py "$(DIST)"

verify-release-artifacts:
	cd "$(DIST)" && sha256sum -c SHA256SUMS
	cd "$(DIST)" && sha256sum -c travelrouter-generic-x86_64-SHA256SUMS
	cd "$(DIST)" && sha256sum -c travelrouter-generic-aarch64-SHA256SUMS
