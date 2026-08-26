# ZeroTier Switch homebrew application
# Requires devkitPro/devkitA64 + libnx.

.SUFFIXES:

ifeq ($(strip $(DEVKITPRO)),)
$(error "Please set DEVKITPRO in your environment")
endif

TOPDIR ?= $(CURDIR)
include $(DEVKITPRO)/libnx/switch_rules

TARGET := zerotier-switch
BUILD := build
SOURCES := source
INCLUDES := include third_party/libzt/include

ARCH := -march=armv8-a+crc+crypto -mtune=cortex-a57 -mtp=soft -fPIE
CXXFLAGS := -g -Wall -O2 -ffunction-sections $(ARCH) $(INCLUDE) -D__SWITCH__ -fno-rtti -fno-exceptions
LDFLAGS := -specs=$(DEVKITPRO)/libnx/switch.specs -g $(ARCH) -Wl,-Map,$(TARGET).map

LIBDIRS := $(PORTLIBS) $(LIBNX) $(CURDIR)/third_party/libzt
# libzt is a C++ static library. Explicitly link the C++ and math runtimes.
# ZeroTier uses std:: containers/exceptions machinery and libm functions such
# as sqrt/expf/sqrtf.
LIBS := -lzt -lstdc++ -lm -lnx

ifneq ($(BUILD),$(notdir $(CURDIR)))

export OUTPUT := $(CURDIR)/$(TARGET)
export TOPDIR := $(CURDIR)
export VPATH := $(foreach dir,$(SOURCES),$(CURDIR)/$(dir))
export DEPSDIR := $(CURDIR)/$(BUILD)

# Discover the application sources while TOPDIR still points at the repository.
# The recursive make below runs from $(BUILD), so this must be rooted at TOPDIR.
CPPFILES := $(foreach dir,$(SOURCES),$(notdir $(wildcard $(TOPDIR)/$(dir)/*.cpp)))
OFILES_SRC := $(CPPFILES:.cpp=.o)

# IMPORTANT: the recursive make receives only exported variables. Export the
# object list explicitly so source/main.cpp becomes source/main.o and is linked.
export OFILES := $(OFILES_SRC)

export INCLUDE := $(foreach dir,$(INCLUDES),-I$(TOPDIR)/$(dir)) \
                  $(foreach dir,$(LIBDIRS),-I$(dir)/include) \
                  -I$(CURDIR)/$(BUILD)
export LIBPATHS := $(foreach dir,$(LIBDIRS),-L$(dir)/lib)

export LD := $(CXX)

export NROFLAGS += --nacp=$(TOPDIR)/$(TARGET).nacp
export APP_TITLE := ZeroTier Switch
export APP_AUTHOR := switch-ldn-zt
export APP_VERSION := 0.1.0
export NACPFLAGS += --titleid=0100000000000A01

.PHONY: all $(BUILD) clean

all: $(BUILD)

$(BUILD):
	@[ -d $@ ] || mkdir -p $@
	@$(MAKE) --no-print-directory -C $(BUILD) -f $(TOPDIR)/Makefile

clean:
	@echo clean ...
	@rm -fr $(BUILD) $(TARGET).nro $(TARGET).nacp $(TARGET).elf $(TARGET).map

else

# We are now inside $(BUILD). OFILES is exported by the outer invocation;
# do not recompute it from the current directory, because source/ is one level up.
DEPENDS := $(OFILES:.o=.d)

all: $(OUTPUT).nro

$(OUTPUT).nro: $(OUTPUT).elf $(OUTPUT).nacp

$(OUTPUT).elf: $(OFILES)
	@echo linking $(notdir $@)
	@$(LINK.o) $(OFILES) $(LIBPATHS) $(LIBS) -o $@

-include $(DEPENDS)

endif
