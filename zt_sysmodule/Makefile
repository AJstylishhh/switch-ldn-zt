# ZeroTier sysmodule (Sys B), title 4200000000000011.
# Phase 1: link libzt only; no zts_* calls yet.

MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ATMOSPHERE_LIBRARIES_DIR := $(abspath $(MAKEFILE_DIR)/../ldn_mitm/Atmosphere-libs)
LIBZT_DIR := $(abspath $(MAKEFILE_DIR)/../third_party/libzt)
include $(ATMOSPHERE_LIBRARIES_DIR)/config/templates/stratosphere.mk

TARGET := zerotier_sys
BUILD := build
SOURCES := source
DATA :=

# Atmosphere/libnx environment plus the isolated Sys B libzt dependency.
LIBDIRS += $(PORTLIBS) $(LIBNX) $(LIBZT_DIR)
INCLUDES += $(DEVKITPRO)/libnx/include

TARGET_VERSION := 0.1.0-b1
CFLAGS += -DZT_SYS_B1
CXXFLAGS += -DZT_SYS_B1

# libzt is linked only by Sys B. No zts_* symbols are referenced in this phase.
LIBS += -lzt -lnx

ifneq ($(BUILD),$(notdir $(CURDIR)))

export OUTPUT := $(CURDIR)/$(TARGET)
export TOPDIR := $(MAKEFILE_DIR)
export VPATH := $(foreach dir,$(SOURCES),$(MAKEFILE_DIR)/$(dir)) $(foreach dir,$(DATA),$(MAKEFILE_DIR)/$(dir))
export DEPSDIR := $(CURDIR)/$(BUILD)

# Phase 1: libzt link plus only the compatibility shims required by libzt.
CFILES := errno_compat.c
CPPFILES := main.cpp zt_compat.cpp
SFILES :=
BINFILES :=

export LD := $(CXX)

export OFILES := $(addsuffix .o,$(BINFILES)) $(CPPFILES:.cpp=.o) $(CFILES:.c=.o) $(SFILES:.s=.o)
export INCLUDE := $(foreach dir,$(INCLUDES),-I$(dir)) $(foreach dir,$(LIBDIRS),-I$(dir)/include) $(foreach dir,$(AMS_LIBDIRS),-I$(dir)/include) -I$(CURDIR)/$(BUILD)
export LIBPATHS := $(foreach dir,$(LIBDIRS),-L$(dir)/lib) $(foreach dir,$(AMS_LIBDIRS),-L$(dir)/lib) $(foreach dir,$(AMS_LIBDIRS),-L$(dir)/$(ATMOSPHERE_LIBRARY_DIR))
# Export an explicit libzt search path as well; the recursive make must retain it.
export LIBPATHS += -L$(LIBZT_DIR)/lib
export BUILD_EXEFS_SRC := $(TOPDIR)/$(EXEFS_SRC)
export APP_JSON := $(TOPDIR)/res/app.json

.PHONY: all $(BUILD) clean
all: $(BUILD)

$(BUILD):
	@[ -d $@ ] || mkdir -p $@
	@$(MAKE) --no-print-directory -C $(BUILD) -f $(MAKEFILE_DIR)/Makefile

clean:
	@rm -fr $(BUILD) $(TARGET).kip $(TARGET).elf $(TARGET).nso $(TARGET).npdm $(TARGET).nsp

else

DEPENDS := $(OFILES:.o=.d)
all: $(OUTPUT).nsp
$(OUTPUT).kip: $(OUTPUT).elf
$(OUTPUT).nsp: $(OUTPUT).nso $(OUTPUT).npdm
$(OUTPUT).elf: $(OFILES)
$(OUTPUT).nso: $(OUTPUT).elf

$(OFILES): $(ATMOSPHERE_LIBRARIES_DIR)/libstratosphere/$(ATMOSPHERE_LIBRARY_DIR)/libstratosphere.a

%.npdm: %.npdm.json
	@npdmtool $< $@

-include $(DEPENDS)
endif
