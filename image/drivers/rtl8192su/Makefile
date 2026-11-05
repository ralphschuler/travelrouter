SHELL := /bin/sh

SOURCE_ROOT ?= $(abspath ../../..)
BUILD_DIR ?= $(SOURCE_ROOT)/build/rtl8192su
OUTPUT_MODULE ?= $(BUILD_DIR)/r92su.ko
KERNEL_RELEASE ?= 6.18.58-0-rpi
KERNEL_PACKAGE_VERSION ?= 6.18.58-r0
KERNEL_DEV_PACKAGE ?= linux-rpi-dev
ALPINE_BRANCH ?= v3.24
APK_ARCH ?= aarch64
KERNEL_PACKAGE_URL ?=
DRIVER_REVISION ?= $(shell tr -d '\n' < UPSTREAM_REVISION)
ARCH ?= arm64
CROSS_COMPILE ?=

.PHONY: all build info

all: build

info:
	@printf '%s\n' \
	  "Upstream revision: $(DRIVER_REVISION)" \
	  "Kernel release: $(KERNEL_RELEASE)" \
	  "Kernel package: $(KERNEL_PACKAGE_VERSION)" \
	  "Header package: $(KERNEL_DEV_PACKAGE)" \
	  "Architecture: $(ARCH)" \
	  "Output module: $(OUTPUT_MODULE)"

build:
	DRIVER_REVISION="$(DRIVER_REVISION)" ARCH="$(ARCH)" CROSS_COMPILE="$(CROSS_COMPILE)" \
	  KERNEL_DEV_PACKAGE="$(KERNEL_DEV_PACKAGE)" ALPINE_BRANCH="$(ALPINE_BRANCH)" \
	  APK_ARCH="$(APK_ARCH)" KERNEL_PACKAGE_URL="$(KERNEL_PACKAGE_URL)" \
	  sh "$(SOURCE_ROOT)/image/build_r92su.sh" "$(SOURCE_ROOT)" "$(BUILD_DIR)" \
	  "$(KERNEL_RELEASE)" "$(KERNEL_PACKAGE_VERSION)" "$(OUTPUT_MODULE)"
