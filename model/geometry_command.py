import struct
import euclid3 as euclid

# =============== Utility Functions ===============

_24bit_to_16bit = lambda components: scale_components(components, 1 / 8, int)

def command(command, parameters=None, tag=None):
    parameters = parameters if parameters else []
    if tag:
        return dict(instruction=command, params=parameters, tag=tag)
    return dict(instruction=command, params=parameters)

def pack_bits(*bit_value_pairs):
    packed_bits = 0
    for pair in bit_value_pairs:
        key, value = pair
        lower, upper = (key, key) if isinstance(key, int) else key
        bit_count = upper - lower + 1
        mask = (bit_count << bit_count) -1
        packed_bits |= (value & mask) << lower
    return packed_bits

def scale_components(components, constant, cast=None):
    if cast:
        return [cast(component * constant) for component in components]
    return [component * constant for component in components]

def texture_size_shift(size):
    shift = 0
    while 8 < size:
        size >>= 1
        shift += 1;
    return shift

def to_fixed_point(float_value, fraction=12):
    return int(float_value * 2 ** fraction)

# =============== Command Functions ===============

def begin_vtxs(format):
    return command(0x40, [struct.pack("<I", format & 0x3)])
    # self.cycles += 1

def color(red, green, blue, use256=False):
    if use256:
        # DS colors are in 16bit mode (5 bits per value)
        red = int(red/8)
        blue = int(blue/8)
        green = int(green/8)
    return command(0x20, [
        struct.pack("<I",
        (red & 0x1F) +
        ((green & 0x1F) << 5) +
        ((blue & 0x1F) << 10))
    ])
    # self.cycles += 1

def dif_amb(diffuse, ambient, setvertex=False, use256=False):
    if use256:
        # DS colors are in 16bit mode (5 bits per value)
        diffuse = _24bit_to_16bit(diffuse)
        ambient = _24bit_to_16bit(ambient)
    cmd = command(0x30, [struct.pack("<I", pack_bits(
        ((0, 4), diffuse[0]),
        ((5, 9), diffuse[1]),
        ((10, 14), diffuse[2]),
        (15, setvertex),
        ((16, 20), ambient[0]),
        ((21, 25), ambient[1]),
        ((26, 30), ambient[2])))])
    # self.cycles += 4
    return cmd

def mtx_mult_4x4(matrix, tag=None):
    return command(0x18, [
            struct.pack("<i",to_fixed_point(matrix.a)), struct.pack("<i",to_fixed_point(matrix.b)), struct.pack("<i",to_fixed_point(matrix.c)), struct.pack("<i",to_fixed_point(matrix.d)),
            struct.pack("<i",to_fixed_point(matrix.e)), struct.pack("<i",to_fixed_point(matrix.f)), struct.pack("<i",to_fixed_point(matrix.g)), struct.pack("<i",to_fixed_point(matrix.h)),
            struct.pack("<i",to_fixed_point(matrix.i)), struct.pack("<i",to_fixed_point(matrix.j)), struct.pack("<i",to_fixed_point(matrix.k)), struct.pack("<i",to_fixed_point(matrix.l)),
            struct.pack("<i",to_fixed_point(matrix.m)), struct.pack("<i",to_fixed_point(matrix.n)), struct.pack("<i",to_fixed_point(matrix.o)), struct.pack("<i",to_fixed_point(matrix.p))
        ], tag=tag)
    # self.cycles += 35

def mtx_scale(sx, sy, sz):
    return command(0x1B, [
            struct.pack("<i", to_fixed_point(sx)),
            struct.pack("<i", to_fixed_point(sy)),
            struct.pack("<i", to_fixed_point(sz))
        ])
    # self.cycles += 22

def normal(x, y, z):
    return command(0x21, [
        struct.pack("<I",
        (int((x*0.95) * 2**9) & 0x3FF) +
        ((int((y*0.95) * 2**9) & 0x3FF) << 10) +
        ((int((z*0.95) * 2**9) & 0x3FF) << 20))
    ])
    # self.cycles += 9 # This is assuming just ONE light is turned on

polygon_mode_modulation = 0
polygon_mode_normal = 0
polygon_mode_decal = 1
polygon_mode_toon_highlight = 2
polygon_mode_shadow = 3
polygon_depth_less = 0
polygon_depth_equal = 1
def polygon_attr(light0=0, light1=0, light2=0, light3=0,
    mode=polygon_mode_modulation, front=1, back=0, new_depth=0,
    farplane_intersecting=1, dot_polygons=0, depth_test=polygon_depth_less,
    fog_enable=1, alpha=31, polygon_id=0):

    attr = pack_bits(
        (0, light0),
        (1, light1),
        (2, light2),
        (3, light3),
        ((4, 5), mode),
        (6, back),
        (7, front),
        (11, new_depth),
        (12, farplane_intersecting),
        (13, dot_polygons),
        (14, depth_test),
        (15, fog_enable),
        ((16, 20), alpha),
        ((24, 29), polygon_id))

    return command(0x29, [struct.pack("<I", attr)])
    # self.cycles += 1

def pop():
    return command(0x12, [struct.pack("<I",0x1)])
    # self.cycles += 36

def push():
    return command(0x11)
    # self.cycles += 17

def spe_emi(specular, emit, use_specular_table=False, use256=False):
    if use256:
        # DS colors are in 16bit mode (5 bits per value)
        specular = _24bit_to_16bit(specular)
        emit = _24bit_to_16bit(emit)
    cmd = command(0x31, [struct.pack("<I", pack_bits(
        ((0, 4), specular[0]),
        ((5, 9), specular[1]),
        ((10, 14), specular[2]),
        (15, use_specular_table),
        ((16, 20), emit[0]),
        ((21, 25), emit[1]),
        ((26, 30), emit[2])))])
    # self.cycles += 4
    return cmd

def texcoord(u, v):
    return command(0x22, [
        struct.pack("<I",
        (int(u * 2**4) & 0xFFFF) |
        ((int(v * 2**4) & 0xFFFF) << 16))])
    # self.cycles += 1

def teximage_param(width, height, offset=0, format=0, palette_transparency=0,
                   transform_mode=0, u_repeat=1, v_repeat=1, u_flip=0, v_flip=0, texture_name=None):
    #texture width/height is coded as Size = (8 << N). Thus, the range is 8..1024 (field size is 3 bits) and only N gets encoded, so we
    #need to convert incoming normal textures to this notation. (ie, 1024 would get written out as 7, since 1024 == (8 << 7))

    width_index = texture_size_shift(width)
    height_index = texture_size_shift(height)

    attr = pack_bits(
        ((0, 15), int(offset / 8)),
        (16, u_repeat),
        (17, v_repeat),
        (18, u_flip),
        (19, v_flip),
        ((20, 22), width_index),
        ((23, 25), height_index),
        ((26, 28), format),
        (29, palette_transparency),
        ((30, 31), transform_mode))
    return command(0x2A, [struct.pack("<I", attr)], texture_name)
    # self.cycles += 1

def texpllt_base(offset, texture_format):
    FOUR_COLOR_PALETTE = 2
    shift = 8 if texture_format == FOUR_COLOR_PALETTE else 16
    return command(0x2B, [struct.pack("<I", pack_bits(((0, 12), offset >> shift) ))])
    # self.cycles += 1

def vtx_10(x, y, z):
    # same as vtx_16, but using 10bit coordinates with 6bit fractional bits;
    # this ends up being somewhat less accurate, but consumes one fewer
    # parameter in the list, and costs one fewer GPU cycle to draw.

    return command(0x24, [
        struct.pack("<I",
        (int(x * 2**6) & 0x3FF) |
        ((int(y * 2**6) & 0x3FF) << 10) |
        ((int(z * 2**6) & 0x3FF) << 20))
    ])
    # self.cycles += 8

def vtx_16(x, y, z):
    # given vertex coordinates as floats, convert them into
    # 16bit fixed point numerals with 12bit fractional parts,
    # and pack them into two commands.

    # note: this command is ignoring overflow completely, do note that
    # values outside of the range (approx. -8 to 8) will produce strange
    # results.

    return command(0x23, [
        struct.pack("<I",
        (int(x * 2**12) & 0xFFFF) |
        ((int(y * 2**12) & 0xFFFF) << 16)),
        struct.pack("<I",(int(z * 2**12) & 0xFFFF))
    ])
    # self.cycles += 9
