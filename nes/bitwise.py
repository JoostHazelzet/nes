"""
Some common bitwise manipulations.
"""


def set_bit(target, bit):
    return target | (1 << bit)

def clear_bit(target, bit):
    return target & ~(1 << bit)

def bit_high(value, bit):
    """
    Returns whether the bit specified is set high in value
    e.g. bit_high(64, 6) == True    (64 = 0b01000000, so bit 6 is high)
         bit_high(64, 2) == False
    """
    return value & (0b00000001 << bit) > 0

def bit_low(value, bit):
    """
    Returns whether the bit specified is set low in value
    e.g. bit_high(64, 6) == False    (64 = 0b01000000, so bit 6 is high)
         bit_high(64, 2) == True
    """
    return value & (0b00000001 << bit) == 0

def replace_high_byte(v, hi_byte):
    return v & 0x00FF + (hi_byte << 8)

def lower_nibble(value):
    """
    Returns the value of the lower nibble of a byte
    """
    return value & 0b00001111

def upper_nibble(value):
    """
    Returns the value of the upper nibble of a byte (i.e. a value in range 0-15)
    """
    return (value & 0b11110000) >> 4