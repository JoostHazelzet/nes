# cython: profile=True, boundscheck=False, nonecheck=False

import logging
from nes import LOG_MEMORY

cdef class MemoryBase:
    """
    Basic memory controller interface
    """
    def __init__(self):
        pass

    cpdef unsigned char read(self, int address):
        raise NotImplementedError()

    cpdef void write(self, int address, unsigned char value):
        raise NotImplementedError()


###### Main Memory #####################################################################################################

DEF NUM_PPU_REGISTERS = 8       # number of ppu registers

# NES Main memory map locations
DEF RAM_END = 0x0800            # NES main ram to here
DEF PPU_END = 0x4000            # PPU registers to here
DEF APU_END = 0x4018            # APU registers (+OAM DMA reg) to here
DEF APU_UNUSED_END = 0x4020     # generally unused APU and I/O functionality
DEF OAM_DMA = 0x4014            # OAM DMA register address
DEF CONTROLLER1 = 0x4016        # port for controller (read controller 1 / write both controllers)
DEF CONTROLLER2 = 0x4017        # port for controller 2 (read only, writes to this port go to the APU)
DEF CART_START = 0x4020         # start of cartridge address space

# OAM memory size for the DMA transfer
from ppu cimport OAM_SIZE_BYTES


cdef class NESMappedRAM(MemoryBase):
    """
    NES memory following NES CPU memory map pattern

    References:
        [1] CPU memory map:  https://wiki.nesdev.com/w/index.php/CPU_memory_map
    """
    def __init__(self, ppu=None, apu=None, cart=None, controller1=None, controller2=None, interrupt_listener=None):
        super().__init__()
        self.ppu = ppu
        self.apu = apu
        self.cart = cart
        self.controller1 = controller1
        self.controller2 = controller2
        self.interrupt_listener = interrupt_listener

        # internal variable used for open bus behaviour
        self._last_bus = 0

    cpdef unsigned char read(self, int address):
        """
        Read one byte of memory from the NES address space
        """
        cdef unsigned char value

        if address < RAM_END:    # RAM and its mirrors
            value = self.ram[address % RAM_SIZE]
        elif address < PPU_END:  # PPU registers
            value = self.ppu.read_register(address % NUM_PPU_REGISTERS)
        elif address < APU_END:
            if address == OAM_DMA:
                # write only
                value = 0
            elif address == CONTROLLER1:
                value = (self.controller1.read_bit() & 0b00011111) + (0x40 & 0b11100000)
                # todo: deal with open bus behaviour of upper control lines
            elif address == CONTROLLER2:
                # todo: deal with open bus behaviour of upper control lines
                value = (self.controller2.read_bit() & 0b00011111) + (0x40 & 0b11100000)
            else:
                # todo: APU registers
                value = 0
        elif address < APU_UNUSED_END:
            # todo: generally unused APU and I/O functionality
            value = 0
        else:
            # cartridge space; pass this to the cart, which might do its own mapping
            value = self.cart.read(address)

        #logging.log(LOG_MEMORY, "read {:04X}  (= {:02X})  region={:10s}".format(address, value, region), extra={"source": "mem"})
        return value

    cpdef void write(self, int address, unsigned char value):
        """
        Write one byte of memory in the NES address space
        """
        #logging.log(LOG_MEMORY, "write {:02X} --> {:04X}".format(value, address), extra={"source": "mem"})

        if address < RAM_END:    # RAM and its mirrors
            self.ram[address % RAM_SIZE] = value
        elif address < PPU_END:  # PPU registers
            register_ix = address % NUM_PPU_REGISTERS
            self.ppu.write_register(register_ix, value)
        elif address < APU_END:
            if address == OAM_DMA:
                self.run_oam_dma(value)
            elif address == CONTROLLER1:
                self.controller1.set_strobe(value)
                self.controller2.set_strobe(value)
            else:
                # todo: APU registers
                pass
        elif address < APU_UNUSED_END:
            # todo: generally unused APU and I/O functionality
            pass
        else:
            # cartridge space; pass this to the cart, which might do its own mapping
            self.cart.write(address, value)

    cdef void run_oam_dma(self, int page):
        """
        OAM DMA copies an entire page (wrapping at the page boundary if the start address in ppu's oam_addr is not zero)
        from RAM to ppu OAM.  This also causes the cpu to pause for 513 or 514 cycles.
        :param page:
        :return:
        """
        #logging.debug("OAM DMA from page {:02X}".format(page), extra={"source": "mem"})

        # done in two parts to correctly account for wrapping at page end
        cdef unsigned char data_block[OAM_SIZE_BYTES]
        cdef int i, addr_base, oam_addr

        oam_addr = self.ppu.oam_addr
        addr_base = page << 8
        for i in range(OAM_SIZE_BYTES):
            data_block[(i + oam_addr) & 0xFF] = self.read( addr_base + i )

        # pass with the size here to avoid zero-terminating as if it were a string
        self.ppu.write_oam(data_block[:OAM_SIZE_BYTES])
        # tell the interrupt listener that the CPU should pause due to OAM DMA
        self.interrupt_listener.raise_oam_dma_pause()

    def __getstate__(self):
        # annoyingly, Cython pickles char arrays as null terminated strings, so we have to do this manually
        ram = self.ram[:RAM_SIZE]
        state = (ram, self._last_bus)
        return state

    def __setstate__(self, state):
        (ram, _last_bus) = state
        for i in range(RAM_SIZE):
            self.ram[i] = ram[i]
        self._last_bus = _last_bus
        return state



###### VRAM ############################################################################################################

cdef class NESVRAM(MemoryBase):
    """
    NES video (PPU) RAM, following the PPU memory map pattern

    References:
        [1] PPU memory map: https://wiki.nesdev.com/w/index.php/PPU_memory_map
    """
    def __init__(self, cart, nametable_size_bytes=2048):
        super().__init__()
        self.cart = cart
        if nametable_size_bytes != NAMETABLES_SIZE_BYTES:
            # There are a few carts that can provide extra nametable space, but that is not yet supported
            raise ValueError("Different sized nametables not implemented")
        self._set_nametable_mirror_pattern()

    cdef _set_nametable_mirror_pattern(self):
        cdef int i
        for i in range(4):
            self.nametable_mirror_pattern[i] = self.cart.nametable_mirror_pattern[i]

    cpdef unsigned char read(self, int address):
        cdef unsigned char value
        cdef int page, offset, true_page

        if address < NAMETABLE_START:
            # pattern table - provided by the rom
            value = self.cart.read_ppu(address)
        elif address < PALETTE_START:
            # nametable
            page = (address - NAMETABLE_START) / NAMETABLE_LENGTH_BYTES # which nametable?
            offset = (address - NAMETABLE_START) % NAMETABLE_LENGTH_BYTES  # offset in that table

            # some of the pages (e.g. 2 and 3) are mirrored, so for these, find the underlying
            # namepage that they point to based on the mirror pattern
            true_page = self.nametable_mirror_pattern[page]
            value = self._nametables[true_page * NAMETABLE_LENGTH_BYTES + offset]
        else:
            # palette table
            if address == 0x3F10 or address == 0x3F14 or address == 0x3F18 or address == 0x3F1C:
                # "addresses $3F10/$3F14/$3F18/$3F1C are mirrors of $3F00/$3F04/$3F08/$3F0C"
                # (https://wiki.nesdev.com/w/index.php/PPU_palettes)
                address -= 0x10
            return self.palette_ram[address % PALETTE_SIZE_BYTES]
        return value

    cpdef void write(self, int address, unsigned char value):
        cdef int page, offset, true_page

        if address < NAMETABLE_START:
            # pattern table - provided by the rom
            self.cart.write_ppu(address, value)  # todo: need something better here via the read_ppu/wrtie_ppu in order to implement mappers
        elif address < PALETTE_START:
            # nametable
            page = int((address - NAMETABLE_START) / NAMETABLE_LENGTH_BYTES)  # which nametable?
            offset = (address - NAMETABLE_START) % NAMETABLE_LENGTH_BYTES  # offset in that table

            # some of the pages (e.g. 2 and 3) are mirrored, so for these, find the underlying
            # namepage that they point to based on the mirror pattern
            true_page = self.nametable_mirror_pattern[page]
            self._nametables[true_page * NAMETABLE_LENGTH_BYTES + offset] = value
        else:
            # palette table
            if address == 0x3F10 or address == 0x3F14 or address == 0x3F18 or address == 0x3F1C:
                # "addresses $3F10/$3F14/$3F18/$3F1C are mirrors of $3F00/$3F04/$3F08/$3F0C"
                # (https://wiki.nesdev.com/w/index.php/PPU_palettes)
                address -= 0x10
            self.palette_ram[address % PALETTE_SIZE_BYTES] = value
