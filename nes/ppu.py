import logging
import time

from .memory import NESVRAM
from .bitwise import bit_high, bit_low, set_bit, clear_bit, replace_high_byte
from nes import LOG_PPU

class NESPPU:
    """
    NES Picture Processing Unit (PPU), the 2C02

    References:
        [1] Overall reference:  https://wiki.nesdev.com/w/index.php/PPU_programmer_reference
        [2] Rendering timing: https://wiki.nesdev.com/w/index.php/PPU_rendering
        [3] OAM layout:  https://wiki.nesdev.com/w/index.php/PPU_OAM

        [4] Detailed operation: http://nesdev.com/2C02%20technical%20operation.TXT

        [5] Palette generator: https://bisqwit.iki.fi/utils/nespalette.php

        [6] Register behaviour: https://wiki.nesdev.com/w/index.php/PPU_registers
    """
    NUM_REGISTERS = 8
    OAM_SIZE_BYTES = 256

    # Register indices
    # (this is not just an enum, this is the offset of the register in the CPU memory map from 0x2000)
    PPU_CTRL = 0
    PPU_MASK = 1
    PPU_STATUS = 2
    OAM_ADDR = 3
    OAM_DATA = 4
    PPU_SCROLL = 5
    PPU_ADDR = 6
    PPU_DATA = 7

    # masks for the bits in ppu registers
    # ppu_status
    VBLANK_MASK =               0b10000000  # same for ppu_ctrl
    SPRITE0_HIT_MASK =          0b01000000
    SPRITE_OVERFLOW_MASK =      0b00100000

    # ppu_ctrl
    SPRITE_SIZE_MASK =          0b00100000
    BKG_PATTERN_TABLE_MASK =    0b00010000
    SPRITE_PATTERN_TABLE_MASK = 0b00001000
    VRAM_INCREMENT_MASK =       0b00000100
    NAMETABLE_MASK =            0b00000011

    # ppu_mask
    RENDERING_ENABLED_MASK =    0b00011000
    RENDER_SPRITES_MASK =       0b00010000
    RENDER_BACKGROUND_MASK =    0b00001000
    RENDER_LEFT8_SPRITES_MASK = 0b00000100
    RENDER_LEFT8_BKG_MASK =     0b00000010
    GREYSCALE_MASK =            0b00000001


    # bit numbers of some important bits in registers
    # ppu_status
    V_BLANK_BIT = 7             # same for ppu_ctrl

    # ppu mask
    RENDER_LEFT8_BKG_BIT = 1
    RENDER_LEFT8_SPRITES_BIT = 2

    # byte numbers in ppu scroll
    PPU_SCROLL_X = 0
    PPU_SCROLL_Y = 1

    # screen and sprite/tile sizes:
    PIXELS_PER_LINE = 341       # number of pixels per ppu scanline; only 256 of thes are visible
    SCREEN_HEIGHT_PX = 240      # visible screen height (number of visible rows)
    SCREEN_WIDTH_PX = 256       # visible screen width (number of visible pixels per row)
    TILE_HEIGHT_PX = int(8)          # height of a tile/standard sprite in pixels
    TILE_WIDTH_PX = int(8)           # width of tile/standard sprite in pixels
    SCREEN_TILE_ROWS = 30       # number of rows of background tiles in a single screen
    SCREEN_TILE_COLS = 32       # number of columns of tiles in a single screen
    PATTERN_BITS_PER_PIXEL = 2  # number of bits used to represent each pixel in the patterns

    # the total size of a tile in the pattern table in bytes (== 16)
    PATTERN_SIZE_BYTES = int(TILE_WIDTH_PX * TILE_HEIGHT_PX * PATTERN_BITS_PER_PIXEL / 8)

    # A NES rgb palette mapping from NES color values to RGB; others are possible.
    DEFAULT_NES_PALETTE = [
        ( 82,  82,  82), (  1,  26,  81), ( 15,  15, 101), ( 35,   6,  99),
        ( 54,   3,  75), ( 64,   4,  38), ( 63,   9,   4), ( 50,  19,   0),
        ( 31,  32,   0), ( 11,  42,   0), (  0,  47,   0), (  0,  46,  10),
        (  0,  38,  45), (  0,   0,   0), (  0,   0,   0), (  0,   0,   0),
        (160, 160, 160), ( 30,  74, 157), ( 56,  55, 188), ( 88,  40, 184),
        (117,  33, 148), (132,  35,  92), (130,  46,  36), (111,  63,   0),
        ( 81,  82,   0), ( 49,  99,   0), ( 26, 107,   5), ( 14, 105,  46),
        ( 16,  92, 104), (  0,   0,   0), (  0,   0,   0), (  0,   0,   0),
        (254, 255, 255), (105, 158, 252), (137, 135, 255), (174, 118, 255),
        (206, 109, 241), (224, 112, 178), (222, 124, 112), (200, 145,  62),
        (166, 167,  37), (129, 186,  40), ( 99, 196,  70), ( 84, 193, 125),
        ( 86, 179, 192), ( 60,  60,  60), (  0,   0,   0), (  0,   0,   0),
        (254, 255, 255), (190, 214, 253), (204, 204, 255), (221, 196, 255),
        (234, 192, 249), (242, 193, 223), (241, 199, 194), (232, 208, 170),
        (217, 218, 157), (201, 226, 158), (188, 230, 174), (180, 229, 199),
        (181, 223, 228), (169, 169, 169), (  0,   0,   0), (  0,   0,   0),
    ]

    def __init__(self, cart=None, screen=None, interrupt_listener=None):

        # Registers
        self.ppu_ctrl = 0
        self.ppu_mask = 0
        self.oam_addr = 0
        self._oam_addr_held = 0         # this holds the oam_addr value at a certain point in the frame, when it is fixed for the whole frame
        self.oam_data = 0
        self.ppu_scroll = bytearray(2)  # this contains x-scroll and y-scroll accumulated over two writes
        #self._ppu_scroll_ix = 0         # this is a double-write register, so keep track of which byte
        self.ppu_addr = 0               # the accumulated **16-bit** address
        #self._ppu_addr_byte = 0         # this is a double-write register, so keep track of which byte
        self._ppu_byte_latch = 0        # latch to keep track of which byte is being written in ppu_scroll and ppu_addr; latch is shared

        # internal latches to deal with open bus and buffering behaviour
        self._ppu_data_buffer = 0  # data to hold buffered reads from VRAM (see read of ppu_data)
        self._io_latch = 0  # last write/valid read of the ppu registers, sometimes reflected in read statuses

        # internal latches used in background rendering
        self._palette = [self.DEFAULT_NES_PALETTE[0:3], self.DEFAULT_NES_PALETTE[3:6]]     # 2 x palette latches
        self._pattern_lo = bytearray(2)  # 2 x 8 bit patterns
        self._pattern_hi = bytearray(2)  # 2 x 8 bit patterns

        # internal memory and latches used in sprite rendering
        self._oam = bytearray(32)      # this is a secondary internal array of OAM used to store sprite that will be active on the next scanline
        self._sprite_pattern = [[None] * 8 for _ in range(8)]
        self._sprite_bkg_priority = [0] * 8

        # some state used in rendering to tell us where on the screen we are drawing
        self.line = 0
        self.pixel = 0
        self.row = 0
        self.col = 0
        #self._bkg_px = 0
        self._t = 0
        self._tN = 0
        self._tX = 0
        self._tY = 0

        # internal statuses
        self.in_vblank = False
        self.sprite_zero_hit = False
        self.sprite_overflow = False

        # status used by emulator
        self.cycles_since_reset = 0
        self.cycles_since_frame = 0  # number of cycles since the frame start
        self.frames_since_reset = 0  # need all three counters (not really, but easier) because frame lengths vary
        self.time_at_new_frame = None

        # memory
        self.vram = NESVRAM(cart=cart)
        self.oam = bytearray(self.OAM_SIZE_BYTES)

        # screen attached to PPU
        self.screen = screen

        # interrupt listener
        self.interrupt_listener = interrupt_listener

        # palette: use the default, but can be replaced using utils.load_palette
        self.rgb_palette = self.DEFAULT_NES_PALETTE
        self.transparent_color = self._get_non_palette_color()
        self._palette_cache = [[None] * 4, [None] * 4]

        # tell the screen what rgb value the ppu is using to represent transparency
        if self.screen:
            self.screen.transparent_color = self.transparent_color

    def invalidate_palette_cache(self):
        self._palette_cache = [[None] * 4, [None] * 4]

    # todo: defunct - remove
    def _get_non_palette_color(self):
        """
        Find a non-palette color in order to represent transparent pixels for blitting
        """
        trans_c = (1, 1, 1)
        while True:
            found = False
            for c in self.rgb_palette:
                if trans_c == c:
                    found = True
                    break
            if not found:
                return trans_c
            else:
                # just explore the grays, there are only 64 colors in palette, so even all
                # greys cannot be represented
                trans_c = (trans_c[0]+1, trans_c[1]+1, trans_c[2]+1)

    @property
    def ppu_status(self):
        """
        The ppu status register value (without io latch noise in lower bits)
        :return:
        """
        return self.VBLANK_MASK * self.in_vblank \
               + self.SPRITE0_HIT_MASK * self.sprite_zero_hit \
               + self.SPRITE_OVERFLOW_MASK * self.sprite_overflow

    def read_register(self, register):
        """
        Read the specified PPU register (and take the correct actions along with that)
        This is mostly (always?) triggered by the CPU reading memory mapped ram at 0x2000-0x3FFF
        "Reading a nominally wrtie-only register will return the latch's current value" [6].
        The "latch" here refers to the capacitance
        of the PPU lines, which leads to some degree of "memory" on the lines, which will hold the last
        value written to a port (including read only ones), or the last value read from a read-only port
        """
        if register == self.PPU_CTRL:
            # write only
            print("WARNING: reading i/o latch")
            return self._io_latch
        elif register == self.PPU_MASK:
            # write only
            print("WARNING: reading i/o latch")
            return self._io_latch
        elif register == self.PPU_STATUS:
            # clear ppu_scroll and ppu_addr latches
            self._ppu_byte_latch = 0   # this is a shared latch between scroll and addr
            #self._ppu_scroll_ix = 0   # ^^^^
            v = self.ppu_status + (0x00011111 & self._io_latch)
            self.in_vblank = False  # clear vblank in ppu_status
            self._io_latch = v
            return v
        elif register == self.OAM_ADDR:
            # write only
            print("WARNING: reading i/o latch")
            return self._io_latch
        elif register == self.OAM_DATA:
            # todo: does not properly implement the weird results of this read during rendering
            v = self.oam[self.oam_addr]
            self._io_latch = v
            return v
        elif register == self.PPU_SCROLL:
            # write only
            print("WARNING: reading i/o latch")
            return self._io_latch
        elif register == self.PPU_ADDR:
            # write only
            print("WARNING: reading i/o latch")
            return self._io_latch
        elif register == self.PPU_DATA:
            if self.ppu_addr < self.vram.PALETTE_START:
                v = self._ppu_data_buffer
                self._ppu_data_buffer = self.vram.read(self.ppu_addr)
            else:
                v = self.vram.read(self.ppu_addr)
                # palette reads will return the palette without buffering, but will put the mirrored NT byte in the read buffer.
                # i.e. reading $3F00 will give you the palette entry at $3F00 and will put the byte in VRAM[$2F00] in the read buffer
                # source: http://forums.nesdev.com/viewtopic.php?t=1721
                self._ppu_data_buffer = self.vram.read(self.ppu_addr - 0x1000)
            self._increment_vram_address()
            self._io_latch = self._ppu_data_buffer
            return v

    def write_register(self, register, value):
        """
        Write one of the PPU registers with byte value and do whatever else that entails
        """
        # need to store the last write because it affects the value read on ppu_status
        # "Writing any value to any PPU port, even to the nominally read-only PPUSTATUS, will fill this latch"  [6]
        self._io_latch = value & 0xFF

        if register == self.PPU_CTRL:
            # write only
            # can trigger an immediate NMI if we are in vblank and the (allow) vblank NMI trigger flag is flipped high
            if self.cycles_since_reset < 29658:
                # writes to ppu_ctrl are ignored at first
                return
            trigger_nmi = self.in_vblank \
                          and (value & self.VBLANK_MASK) > 0 \
                          and (self.ppu_ctrl & self.VBLANK_MASK) == 0
            self.ppu_ctrl = value & 0xFF
            #self._t = (self._t & 0b111001111111111) + ((value & 0b00000011) << 10)
            self._tN = value & 0b00000011
            if trigger_nmi:
                self._trigger_nmi()
        elif register == self.PPU_MASK:
            # write only
            self.ppu_mask = value & 0xFF
        elif register == self.PPU_STATUS:
            # read only
            pass
        elif register == self.OAM_ADDR:
            # write only
            self.oam_addr = value & 0xFF
        elif register == self.OAM_DATA:
            # read/write
            self.oam[self.oam_addr] = value
            self.oam_addr = (self.oam_addr + 1) & 0xFF
        elif register == self.PPU_SCROLL:
            # write only
            self.ppu_scroll[self._ppu_byte_latch] = value
            # flip which byte is pointed to on each write; reset on ppu status read
            #self._ppu_scroll_ix = 1 - self._ppu_scroll_ix
            if self._ppu_byte_latch == 0:
                #print("wxs:", value, ((value & 0b11111000) >> 3), self._t)
                #self._t = (self._t & 0b1111111111100000) + ((value & 0b11111000) >> 3)
                #print(self._t)
                self._tX = (value & 0b11111000) >> 3
            else:
                #self._t = (self._t & 0b000110000011111) + ((value & 0b00000111) << 12) + ((value & 0b11111000) << 2)
                self._tY = (value & 0b11111000) >> 3
            self._ppu_byte_latch = 1 - self._ppu_byte_latch

        elif register == self.PPU_ADDR:
            # write only
            # high byte first
            if self._ppu_byte_latch == 0:
                self.ppu_addr = (self.ppu_addr & 0x00FF) + (value << 8)

                #self._t = (self._t & 0b1100000011111111) + ((value & 0b00111111) << 8)
                self._tY = (self._tY & 0b10000) + (value & 0b1111)
            else:
                self.ppu_addr = (self.ppu_addr & 0xFF00) + value
                #self._t = (self._t & 0xFF00) + (value & 0x00FF)
                self._tY = (self._tY & 0b00111) + (value & 0b11)
                self._tN = (value & 0b00001100) >> 2       # SMB relies on this behaviour

                # todo: could we just reset the N value in ppu_ctrl here, since that is write only?
                # I think so...

            # flip which byte is pointed to on each write; reset on ppu status read
            #self._ppu_addr_byte = 1 - self._ppu_addr_byte
            self._ppu_byte_latch = 1 - self._ppu_byte_latch
        elif register == self.PPU_DATA:
            # read/write
            self.vram.write(self.ppu_addr, value)
            self._increment_vram_address()
            if self.ppu_addr >= self.vram.PALETTE_START:
                self.invalidate_palette_cache()

    def _increment_vram_address(self):
        self.ppu_addr += 1 if (self.ppu_ctrl & self.VRAM_INCREMENT_MASK) == 0 else 32

    def _trigger_nmi(self):
        self.interrupt_listener.raise_nmi()

    def _prefetch_active_sprites(self, line):
        """
        Non cycle-correct detector for active sprites on the given line.  Returns a list of the indices of the start
        address of the sprite in the OAM
        """
        # scan through the sprites, starting at oam_start_addr, seeing if they are visible in the line given
        # (note that should be the next line); if so, add them to the list of active sprites, until that gets full.
        # if using 8x16 sprites (True), or 8x8 sprite (False)
        double_sprites = (self.ppu_ctrl & self.SPRITE_SIZE_MASK) > 0
        sprite_height = 16 if double_sprites else 8

        self._active_sprites = []
        sprite_line = []
        for n in range(64):
            addr = (self._oam_addr_held + n * 4) % self.OAM_SIZE_BYTES
            sprite_y = self.oam[addr]
            if sprite_y <= line < sprite_y + sprite_height:
                self._active_sprites.append(addr)
                sprite_line.append(line - sprite_y)
                if len(self._active_sprites) >= 9:
                    break
        if len(self._active_sprites) > 8:
            # todo: this implements the *correct* behaviour of sprite overflow, but not the buggy behaviour
            # (and even then it is not cycle correct, so could screw up games that rely on timing of this very exactly)
            self.sprite_overflow = True
            self._active_sprites = self._active_sprites[:8]
            sprite_line = sprite_line[:8]

        self._fill_sprite_latches(self._active_sprites, sprite_line, double_sprites)

    def _fill_sprite_latches(self, active_sprite_addrs, sprite_line, double_sprites):
        """
        Non cycle-correct way to pre-fetch the sprite lines for the next scanline
        :param active_sprite_addrs:
        :param sprite_line:
        :param double_sprites:
        :return:
        """
        table_base = ((self.ppu_ctrl & self.SPRITE_PATTERN_TABLE_MASK) > 0) * 0x1000

        for i, address in enumerate(active_sprite_addrs):
            attribs = self.oam[(address + 2) & 0xFF]
            palette_ix = attribs & 0b00000011
            palette = self.decode_palette(palette_ix, is_sprite=True)
            flip_v = bit_high(attribs, bit=7)
            flip_h = bit_high(attribs, bit=6)
            self._sprite_bkg_priority[i] = bit_high(attribs, bit=5)

            if not double_sprites:
                tile_ix = self.oam[(address + 1) & 0xFF]
                line = sprite_line[i] if not flip_v else 7 - sprite_line[i]
            else:
                line = sprite_line[i] if not flip_v else 15 - sprite_line[i]
                tile_ix = self.oam[(address + 1) & 0xFF] & 0b11111110
                if line >= 8:
                    tile_ix += 1  # in the lower tile
                    line -= 8

            tile_base = table_base + tile_ix * self.PATTERN_SIZE_BYTES
            sprite_pattern_lo = self.vram.read(tile_base + line)
            sprite_pattern_hi = self.vram.read(tile_base + 8 + line)

            for x in range(8):
                c = bit_high(sprite_pattern_hi, x) * 2 + bit_high(sprite_pattern_lo, x)
                self._sprite_pattern[i][x if flip_h else 7 - x] = palette[c] if c else None

            #print(self.line, i, sprite_line[i], self._sprite_pattern[i], self.oam[address + 3], self._sprite_bkg_priority[i])

    def _overlay_sprites(self, bkg_pixel):
        """
        Cycle-correct (ish) sprite rendering for the pixel at y=line, pixel=pixel.  Includes sprite 0 collision detection.
        """
        c_out = bkg_pixel
        if (self.ppu_mask & self.RENDER_SPRITES_MASK) == 0 \
            or (self.pixel - 1 < 8 and bit_low(self.ppu_mask, self.RENDER_LEFT8_SPRITES_BIT)):
            return c_out

        sprite_c_out, top_sprite = None, None
        s0_visible = False
        for i in reversed(range(len(self._active_sprites))):
            # render in reverse to make overwriting easier
            sprite_addr = self._active_sprites[i]
            sprite_x = self.oam[sprite_addr + 3]
            if sprite_x <= self.pixel - 1 < sprite_x + 8:
                #print(self.line, i, sprite_x, sprite_addr, self._sprite_bkg_priority[i])
                pix = self.pixel - 1 - sprite_x
                # this sprite is visible now
                c = self._sprite_pattern[i][pix]
                if c:
                    top_sprite = i
                    sprite_c_out = c
                    if sprite_addr == 0:
                        s0_visible = True

        # sprite zero collision detection
        # Details: https://wiki.nesdev.com/w/index.php/PPU_OAM#Sprite_zero_hits
        if s0_visible and bkg_pixel != self.transparent_color:
            # todo: there are some more fine details here
            self.sprite_zero_hit = True

        # now decide whether to keep sprite or bkg pixel
        if sprite_c_out and (not self._sprite_bkg_priority[top_sprite] or bkg_pixel == self.transparent_color):
            c_out = sprite_c_out

        return c_out if c_out != self.transparent_color else self.decode_palette(0)[0]  # background color

    def run_cycles(self, num_cycles):
        # cycles correspond to screen pixels during the screen-drawing phase of the ppu
        # there are three ppu cycles per cpu cycles, at least on NTSC systems
        frame_ended = False
        for cyc in range(num_cycles):
            # current scanline of the frame we are on - this determines behaviour during the line
            if self.line <= 239 and (self.ppu_mask & self.RENDERING_ENABLED_MASK) > 0:
                # visible scanline
                if 0 < self.pixel <= 256:  # pixels 1 - 256
                    # render pixel - 1
                    if (self.pixel - 1) % 8 == 0 and self.pixel > 1:
                        # fill background data latches
                        # todo: this is not cycle-correct, since the read is done atomically at the eighth pixel rather than throughout the cycle.
                        self.shift_bkg_latches()  # move the data from the upper latches into the current ones
                        self.fill_bkg_latches(self.line, self.col + 1)   # get some more data for the upper latches
                    # render background from latches
                    bkg_pixel = self._get_bkg_pixel()
                    # overlay srpite from latches
                    final_pixel = self._overlay_sprites(bkg_pixel)
                    if final_pixel != self.transparent_color:
                        self.screen.write_at(x=self.pixel - 1, y=self.line, color=final_pixel)
                elif self.pixel == 257:   # pixels 257 - 320
                    # sprite data fetching: fetch data from OAM for sprites on the next scanline
                    self._prefetch_active_sprites(self.line + 1)
                elif 321 <= self.pixel <= 336:   # pixels 321 - 336
                    # fill background data latches with data for first two tiles of next scanline
                    if self.pixel % 8 == 1:  # will happen at 321 and 329
                        # fill latches
                        self.shift_bkg_latches()  # move the data from the upper latches into the current ones
                        self.fill_bkg_latches(self.line + 1, int((self.pixel - 321) / 8))  # get some more data for the upper latches
                else:  # pixels 337 - 340
                    # todo: unknown nametable fetches (used by MMC5)
                    self._bkg_px = 0

            if self.line == 0 and self.pixel == 65:
                # The OAM address is fixed after this point  [citation needed]
                self._oam_addr_held = self.oam_addr
            elif self.line == 240 and self.pixel == 0:
                # post-render scanline, ppu is idle
                # in this emulator, this is when we render the screen
                # self.render_screen()
                pass
            elif self.line == 241 and self.pixel == 1:
                # set vblank flag
                self.in_vblank = True   # set the vblank flag in ppu_status register
                # trigger NMI (if NMI is enabled)
                if (self.ppu_ctrl & self.VBLANK_MASK) > 0:
                    self._trigger_nmi()
            elif self.line <= 260:
                # during vblank, ppu does no memory accesses; most of the CPU accesses happens here
                pass
            elif self.line == 261:
                # pre-render scanline for next frame; at dot 1, reset vblank flag in ppu_status
                if self.pixel == 1:
                    self.in_vblank = False
                    self.sprite_zero_hit = False
                    self.sprite_overflow = False
                elif self.pixel == 257:
                    # load sprite data for next scanline
                    self._prefetch_active_sprites(line=0)
                elif 321 <= self.pixel <= 336:
                    # load data for next scanline
                    if self.pixel % 8 == 1:  # will happen at 321 and 329
                        # fill latches
                        self.shift_bkg_latches()  # move the data from the upper latches into the current ones
                        self.fill_bkg_latches(line=0, col=int((self.pixel - 321) / 8))  # get some more data for the upper latches
                elif self.pixel == self.PIXELS_PER_LINE - 1 - self.frames_since_reset % 2:
                    # this is the last pixel in the frame, so trigger the end-of-frame
                    # (do it below all the counter updates below, though)
                    frame_ended=True

            if (self.line==15 and self.pixel==256) or (self.line==239 and self.pixel==256):
                print()
                print(self.line, self.pixel)

                print("ppu scroll", (self.ppu_scroll[self.PPU_SCROLL_X] & 0b11111000) >> 3)
                print("nx0 ny0", bit_high(self.ppu_ctrl, 0), bit_high(self.ppu_ctrl, 1))

                total_row = (self.row + bit_high(self.ppu_ctrl, 1) * self.SCREEN_TILE_ROWS + (
                (self.ppu_scroll[self.PPU_SCROLL_Y] & 0b11111000) >> 3)) % (2 * self.SCREEN_TILE_ROWS)
                total_col = (self.col + bit_high(self.ppu_ctrl, 0) * self.SCREEN_TILE_COLS + (
                (self.ppu_scroll[self.PPU_SCROLL_X] & 0b11111000) >> 3)) % (2 * self.SCREEN_TILE_COLS)

                print("total row, col", total_row, total_col)

                ny = int(total_row / self.SCREEN_TILE_ROWS)
                nx = int(total_col / self.SCREEN_TILE_COLS)

                print("nx ny", nx, ny)

                tile_row = total_row - ny * self.SCREEN_TILE_ROWS
                tile_col = total_col - nx * self.SCREEN_TILE_COLS

                print("tile row, col", tile_row, tile_col)

                print("T: nn, YYYYY, XXXXX", self._tN, self._tY, self._tX)


                ntbl_base = self.vram.NAMETABLE_START + (ny * 2 + nx) * self.vram.NAMETABLE_LENGTH_BYTES
                tile_addr = ntbl_base + tile_row * self.SCREEN_TILE_COLS + tile_col

                print(ntbl_base, tile_addr)

            self.cycles_since_reset += 1
            self.cycles_since_frame += 1
            self.pixel += 1
            if self.pixel > 1 and self.pixel % 8 == 1:
                self.col += 1
            if self.pixel >= self.PIXELS_PER_LINE:
                self.line += 1
                self.pixel = 0
                self.col = 0
                if self.line > 0 and self.line % 8 == 0:
                    self.row += 1

            if frame_ended:
                self._new_frame()

            #logging.log(LOG_PPU, self.log_line(), extra={"source": "PPU"})
        return frame_ended

    def fill_bkg_latches(self, line, col):
        """
        Fill the ppu's rendering latches with the next tile to be rendered
        :return:
        """
        # todo: optimization - a lot of this can be precalculated once and then invalidated if anything changes, since that might only happen once per frame (or never)
        # get the tile from the nametable
        row = int(line / 8)


        # x and y coords of the nametable
        # todo: ny0 is wrong here
        #nx0, ny0 = bit_high(self.ppu_ctrl, 0), 0 #bit_high(self.ppu_ctrl, 0), bit_high(self.ppu_ctrl, 1)


        nx0 = bit_high(self._tN, 0)
        ny0 = bit_high(self._tN, 1)

        total_row = (row + ny0 * self.SCREEN_TILE_ROWS + ((self.ppu_scroll[self.PPU_SCROLL_Y] & 0b11111000) >> 3)) % (2 * self.SCREEN_TILE_ROWS)
        total_col = (col + nx0 * self.SCREEN_TILE_COLS + ((self.ppu_scroll[self.PPU_SCROLL_X] & 0b11111000) >> 3)) % (2 * self.SCREEN_TILE_COLS)

        ny = int(total_row / self.SCREEN_TILE_ROWS)
        nx = int(total_col / self.SCREEN_TILE_COLS)

        tile_row = total_row - ny * self.SCREEN_TILE_ROWS
        tile_col = total_col - nx * self.SCREEN_TILE_COLS

        ntbl_base = self.vram.NAMETABLE_START + (ny * 2 + nx) * self.vram.NAMETABLE_LENGTH_BYTES
        tile_addr = ntbl_base + tile_row * self.SCREEN_TILE_COLS + tile_col

        #print(row, total_row,  "x", col, total_col,  ":", (ny * 2 + nx), (self.ppu_ctrl & self.NAMETABLE_MASK))


        #ntbl_base = self.vram.NAMETABLE_START + (self.ppu_ctrl & self.NAMETABLE_MASK) * self.vram.NAMETABLE_LENGTH_BYTES
        #tile_addr = ntbl_base + row * self.SCREEN_TILE_COLS + col

        try:
            tile_index = self.vram.read(tile_addr)
        except:
            print(row, total_row, "x", col, total_col, ":", (ny * 2 + nx), (self.ppu_ctrl & self.NAMETABLE_MASK))

            pass

        tile_bank = (self.ppu_ctrl & self.BKG_PATTERN_TABLE_MASK) > 0
        table_base = tile_bank * 0x1000
        tile_base = table_base + tile_index * self.PATTERN_SIZE_BYTES

        attribute_byte = self.vram.read(ntbl_base
                                        + self.vram.ATTRIBUTE_TABLE_OFFSET
                                        + (int(tile_row / 4) * 8 + int(tile_col / 4))
                                        )

        shift = 4 * (int(tile_row / 2) % 2) + 2 * (int(tile_col / 2) % 2)
        mask = 0b00000011 << shift
        palette_id = (attribute_byte & mask) >> shift

        self._palette[1] = self.decode_palette(palette_id, is_sprite=False)

        tile_line = line - 8 * row
        self._pattern_lo[1] = self.vram.read(tile_base + tile_line)
        self._pattern_hi[1] = self.vram.read(tile_base + tile_line + 8)

        #self._pattern_lo = replace_high_byte(self._pattern_lo, self.vram.read(tile_base + tile_line))
        #self._pattern_hi = replace_high_byte(self._pattern_hi, self.vram.read(tile_base + tile_line + 8))

    def shift_bkg_latches(self):
        self._palette[0] = self._palette[1]
        self._pattern_lo[0] = self._pattern_lo[1]
        self._pattern_hi[0] = self._pattern_hi[1]
        #self._pattern_lo >>= 1
        #self._pattern_hi >>= 1

    def _get_bkg_pixel(self):
        # the data we need is in the zero indices of the latches
        if (   self.ppu_mask & self.RENDER_BACKGROUND_MASK) == 0 \
            or (self.pixel - 1 < 8 and bit_low(self.ppu_mask, self.RENDER_LEFT8_BKG_BIT)):
            return self.transparent_color

        mask = 1 << (7 - (self.pixel - 1) % 8)
        v = ((self._pattern_lo[0] & mask) > 0) + ((self._pattern_hi[0] & mask) > 0) * 2

        #v = bit_high(0, self._pattern_lo) + bit_high(0, self._pattern_hi) * 2

        return self._palette[0][v] if v > 0 else self.transparent_color

    def log_line(self):
        log = "{:5d}, {:3d}, {:3d}   ".format(self.frames_since_reset, self.line, self.pixel)
        log += "C:{:02X} M:{:02X} S:{:02X} OA:{:02X} OD:{:02X} ".format(self.ppu_ctrl,
                                                                                  self.ppu_mask,
                                                                                  self.ppu_status,
                                                                                  self.oam_addr,
                                                                                  self.oam_data)

        log += "SC:{:02X},{:02X} PA:{:04X}".format(self.ppu_scroll[0],
                                                                   self.ppu_scroll[1],
                                                                   self.ppu_addr)

        return log

    def _new_frame(self):
        """
        Things to do at the start of a frame
        """
        self.frames_since_reset += 1
        self.cycles_since_frame = 0
        self.pixel = 0
        self.line = 0
        self.row = 0
        self.col = 0

        #logging.log(logging.INFO, "PPU frame {} starting".format(self.frames_since_reset), extra={"source": "PPU"})

        # todo: "Vertical scroll bits are reloaded if rendering is enabled" - don't know what this means
        # maybe resets/loads bits 1 and 0 of ppu_ctrl, which controls the base nametable

    def decode_palette(self, palette_id, is_sprite=False):
        """
        If is_sprite is true, then decodes palette from the sprite palettes, otherwise
        decodes from the background palette tables.
        """

        if self._palette_cache[is_sprite][palette_id]:
            return self._palette_cache[is_sprite][palette_id]

        # get the palette colours (these are in hue (chroma) / value (luma) format.)
        # palette_id is in range 0..3, and gives an offset into one of the four background palettes,
        # each of which consists of three colors, each of which is represented by a singe byte
        palette_address = self.vram.PALETTE_START + 16 * is_sprite + 4 * palette_id
        palette = []
        for i in range(4):
            palette.append(self.rgb_palette[self.vram.read(palette_address + i) & 0b00111111])
        self._palette_cache[is_sprite][palette_id] = palette
        return palette






    ################################## DEFUNCT RENDER SCREEN FUNCTIONS ####################################

    def render_screen(self):
        """
        Render the screen in a single go
        """
        # clear to the background color
        background_color = self.rgb_palette[self.vram.read(self.vram.PALETTE_START)]
        self.screen.clear(color=background_color)

        # render the background tiles
        self.render_background()

        # render the sprite tiles
        self.render_sprites()

        # show the screen
        self.screen.show()

    def render_background(self):
        """
        Reads the nametable and attribute table and then sends the result of that for each
        tile on the screen to render_tile to actually render the tile (reading the pattern tables, etc.)
        """
        # which nametable is active?
        nametable = self.ppu_ctrl & self.NAMETABLE_MASK
        addr_base = self.vram.NAMETABLE_START + nametable * self.vram.NAMETABLE_LENGTH_BYTES
        for row in range(self.SCREEN_TILE_ROWS):
            vblock = int(row / 2)
            v_subblock_ix = vblock % 2
            for col in range(self.SCREEN_TILE_COLS):
                # todo: do we need to deal with scrolling and mirroring here?
                tile_index = self.vram.read(addr_base + row * self.SCREEN_TILE_COLS + col)

                # get attribute byte from the attribute table at the end of the nametable
                # these tables compress the palette id into two bits for each 2x2 tile block of 16x16px.
                # the attribute bytes each contain the palette id for a 2x2 block of these 16x16 blocks
                # so get the correct byte and then extract the actual palette id from that
                hblock = int(col / 2)
                attribute_byte = self.vram.read(addr_base
                                                + self.vram.ATTRIBUTE_TABLE_OFFSET
                                                + (int(vblock / 2) * 8 + int(hblock / 2))
                                                )
                h_subblock_ix = hblock % 2
                shift = 4 * v_subblock_ix + 2 * h_subblock_ix
                mask = 0b00000011 << shift
                palette_id = (attribute_byte & mask) >> shift
                palette = self.decode_palette(palette_id, is_sprite=False)
                # ppu_ctrl tells us whether to read the left or right pattern table, so let's fetch that
                tile_bank = (self.ppu_ctrl & self.BKG_PATTERN_TABLE_MASK) > 0
                tile = self.decode_tile(tile_index, tile_bank, palette)
                self.screen.render_tile(col * 8, row * 8, tile)

    def decode_tile(self, tile_index, tile_bank, palette, flip_h=False, flip_v=False):
        """
        Decodes a tile given by tile_index from the pattern table specified by tile_bank to an array of RGB color value,
        using the palette supplied.  Transparent pixels (value 0 in the tile) are replaced with self.transparent_color.
        This makes them ready to be blitted to the screen.
        """
        # now decode the tile
        table_base = tile_bank * 0x1000

        # tile index tells us which pattern table to read
        tile_base = table_base + tile_index * self.PATTERN_SIZE_BYTES

        # the (palettized) tile is stored as 2x8byte bit planes, each representing an 8x8 bitmap of depth 1 bit
        # tile here is indexed tile[row][column], *not* tile[x][y]
        tile = [[0] * self.TILE_WIDTH_PX for _ in range(self.TILE_HEIGHT_PX)]

        # todo: this is not very efficient; should probably pre-decode all these tiles as this is slow

        for y in range(self.TILE_HEIGHT_PX):
            for x in range(self.TILE_WIDTH_PX):
                xx = x if not flip_h else self.TILE_WIDTH_PX - 1 - x
                yy = y if not flip_v else self.TILE_HEIGHT_PX - 1 - y
                pixel_color_ix = 0
                for plane in range(2):
                    pixel_color_ix += ((self.vram.read(tile_base + plane * 8 + y) & (0x1 << (7 - x))) > 0) * (plane + 1)
                tile[yy][xx] = palette[pixel_color_ix] if pixel_color_ix > 0 else self.transparent_color
        return tile

    def decode_oam(self):
        """
        Reads the object attribute memory (OAM) to get info about the sprites.  Decodes them and returns
        a list of the sprites in priority order as (x, y, tile, bkg_priority) tuples.
        """
        sprites = []

        # if using 8x16 sprites (True), or 8x8 sprite (False)
        double_sprites = (self.ppu_ctrl & self.SPRITE_SIZE_MASK) > 0
        # pattern table to use for 8x8 sprites, ignored for 8x16 sprites
        tile_bank = (self.ppu_ctrl & self.SPRITE_PATTERN_TABLE_MASK) > 0

        # start here in the OAM
        address = self._oam_addr_held
        for i in range(64):   # up to 64 sprites in OAM  (= 256 bytes / 4 bytes per sprite)
            y = self.oam[address & 0xFF]
            attribs = self.oam[(address + 2) & 0xFF]
            palette_ix = attribs & 0b00000011
            palette = self.decode_palette(palette_ix, is_sprite=True)
            flip_v       = bit_high(attribs, bit=7)      # (attribs & 0b10000000) > 0
            flip_h       = bit_high(attribs, bit=6)      # (attribs & 0b01000000) > 0
            bkg_priority = bit_high(attribs, bit=5)      # (attribs & 0b00100000) > 0
            if not double_sprites:
                tile_ix = self.oam[(address + 1) & 0xFF]
                tile = self.decode_tile(tile_ix, tile_bank, palette, flip_h, flip_v)
            else:
                tile_upper_ix = self.oam[(address + 1) & 0xFF] & 0b11111110
                tile_upper = self.decode_tile(tile_upper_ix, tile_bank, palette, flip_h, flip_v)
                tile_lower = self.decode_tile(tile_upper_ix + 1, tile_bank, palette, flip_h, flip_v)
                tile = tile_upper + tile_lower if not flip_v else tile_lower + tile_upper
            #print((address + 3) & 0xFF)
            x = self.oam[(address + 3) & 0xFF]
            sprites.append((x, y, tile, bkg_priority))
            address += 4
        return sprites

    def render_sprites(self):
        """
        Renders the sprites all in one go.  Still a work in progress!
        """
        # todo: currently renders all sprites on top of everything, starting with lowest priority
        # todo: there are at least two major problems with this:
        #   1. No background priority
        #   2. No max number of sprites
        sprites = self.decode_oam()
        for (x, y, tile, bkg_priority) in reversed(sprites):
            self.screen.render_tile(x, y, tile)


"""
Development Notes
-----------------

Improvements and Corrections
----------------------------
  - Critical:  Performance


  - Error:  Sprites are (I think) one line high and a few (one?) pixels left of correct (or the background is left/right by a pixel or so)
             \-- Almost certain bkg or sprites (probably bkg?) are off by 1px based on sprite 0 in SMB (should be under the coin)
            THINK THIS IS NOW CORRECTED

  - Error:  Test failures:
             |-- BRK test failure
             \-- VBlank timing
  - Error:  SMB status bar last few pixels get scrolled
             \-- timing error or off-by-one-line error, I think

  - Major:  Tidy up handling of _tN
  - Major:  Scrolling
             |-- fine x/y scrolling
             \-- test y scrolling (coarse and fine)
  - Major:  Test coverage
             |-- try more test ROMS
             \-- automation of some testing

  - Medium:  Greyscale mode
  - Medium:  Open bus behaviour on memory
  - Medium:  Colours boost if ppu_mask bits set

  - Minor:  Background palette hack
  - Minor:  OAMDATA read behaviour during render
  - Minor:  Sprite priority quirk

  - Unknown: Vertical scroll bits reloaded at cycles 280-304 of scanline 261 (see _new_frame())

"""
