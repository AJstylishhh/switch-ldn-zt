# Minimal Atmosphere sysmodule for isolating libzt from ldn_mitm.
# Sys B: title 4200000000000011.

ATMOSPHERE_LIBRARIES_DIR := $(abspath $(CURDIR)/../ldn_mitm/Atmosphere-libs)
include $(ATMOSPHERE_LIBRARIES_DIR)/config/templates/stratosphere.mk

TARGET := zerotier_sys
BUILD := build
SOURCES := source
DATA :=
INCLUDES := $(CURDIR)/../third_party/libzt/include

TARGET_VERSION := 0.1.0-b1
CFLAGS += -DZT_SYS_B1
CXXFLAGS += -DZT_SYS_B1
LIBDIRS += $(abspath $(CURDIR)/../third_party/libzt)
LIBS += -Wl,--whole-archive -lzt -Wl,--no-whole-archive

ifneq ($(BUILD),$(notdir $(CURDIR)))

export OUTPUT := $(CURDIR)/$(TARGET)
export TOPDIR := $(CURDIR)
export VPATH := $(foreach dir,$(SOURCES),$(CURDIR)/$(dir)) $(foreach dir,$(DATA),$(CURDIR)/$(dir))
export DEPSDIR := $(CURDIR)/$(BUILD)

CFILES := $(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.c)))
CPPFILES := $(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.cpp)))
SFILES := $(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.s)))
BINFILES := $(foreach dir,$(DATA),$(notdir $(wildcard $(dir)/*.*)))

ifeq ($(strip $(CPPFILES)),)
export LD := $(CC)
else
export LD := $(CXX)
endif

export OFILES := $(addsuffix .o,$(BINFILES)) $(CPPFILES:.cpp=.o) $(CFILES:.c=.o) $(SFILES:.s=.o)
export INCLUDE := $(foreach dir,$(INCLUDES),-I$(dir)) $(foreach dir,$(LIBDIRS),-I$(dir)/include) $(foreach dir,$(AMS_LIBDIRS),-I$(dir)/include) -I$(CURDIR)/$(BUILD)
export LIBPATHS := $(foreach dir,$(LIBDIRS),-L$(dir)/lib) $(foreach dir,$(AMS_LIBDIRS),-L$(dir)/lib) $(foreach dir,$(AMS_LIBDIRS),-L$(dir)/$(ATMOSPHERE_LIBRARY_DIR))
export BUILD_EXEFS_SRC := $(TOPDIR)/$(EXEFS_SRC)
export APP_JSON := $(TOPDIR)/res/app.json

.PHONY: all $(BUILD) clean
all: $(BUILD)

$(BUILD):
	@[ -d $@ ] || mkdir -p $@
	@$(MAKE) --no-print-directory -C $(BUILD) -f $(CURDIR)/Makefile

clean:
	@rm -fr $(BUILD) $(TARGET).kip $(TARGET).elf $(TARGET).nso $(TARGET).npdm $(TARGET).nsp

else

DEPENDS := $(OFILES:.o=.d)
all: $(OUTPUT).nsp
$(OUTPUT).kip: $(OUTPUT).elf
$(OUTPUT).nsp: $(OUTPUT).nso $(OUTPUT).npdm
$(OUTPUT).nso: $(OUTPUT).elf
$(OUTPUT).elf: $(OFILES)

$(OFILES): $(ATMOSPHERE_LIBRARIES_DIR)/libstratosphere/$(ATMOSPHERE_LIBRARY_DIR)/libstratosphere.a

%.npdm: %.npdm.json
	@npdmtool $< $@

-include $(DEPENDS)
endif
