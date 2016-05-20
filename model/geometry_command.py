import struct
import euclid3 as euclid

# =============== Utility Functions ===============

_24bit_to_16bit = lambda components: scale_components(components, 1 / 8, int)

def command(command, parameters=None):
    parameters = parameters if parameters else []
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

def teximage_param(width, height, offset=0, format=0, palette_transparency=0,
    transform_mode=0, u_repeat=1, v_repeat=1, u_flip=0, v_flip=0):
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
    return command(0x2A, [struct.pack("<I", attr)])
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

# Emitter: caches and writes commands for the GX
# engine, with proper command packing when applicible.
# note: *does not* know which commands require which
# parameters-- make sure you're passing in the correct
# amounts or the real DS hardware will be freaking out
class Emitter:
    def __init__(self):
        self.commands = []
        self.offset = 0
        self.cycles = 0

    def command(self, command, parameters = []):
        cmd = {'instruction': command, 'params': parameters}
        self.commands.append(cmd)
        self.offset += 1 + len(parameters)
        return cmd

    def write(self, packed=False):
        # todo: modify this heavily, allow packed commands
        out = bytes()
        commands = self.commands
        while len(commands) > 0:
            # pad the command with 0's for unpacked mode
            if packed:
                if len(commands) >= 4 and len(commands[3]['params']) > 0:
                    #pack the next 4 commands
                    out += struct.pack("<BBBB", commands[0]['instruction'], commands[1]['instruction'], commands[2]['instruction'], commands[3]['instruction'])
                    for i in range(4):
                        for param in commands[i]['params']:
                            out += param
                    commands = commands[4:]
                elif len(commands) >= 3 and len(commands[2]['params']) > 0:
                    #pack the next 3 commands
                    out += struct.pack("<BBBB", commands[0]['instruction'], commands[1]['instruction'], commands[2]['instruction'], 0)
                    for i in range(3):
                        for param in commands[i]['params']:
                            out += param
                    commands = commands[3:]
                elif len(commands) >= 2 and len(commands[1]['params']) > 0:
                    #pack the next 3 commands
                    out += struct.pack("<BBBB", commands[0]['instruction'], commands[1]['instruction'], 0, 0)
                    for i in range(2):
                        for param in commands[i]['params']:
                            out += param
                    commands = commands[2:]
                else:
                    #output this command as unpacked
                    out += struct.pack("<BBBB", commands[0]['instruction'], 0,0,0)
                    for param in commands[0]['params']:
                        out += param
                    commands = commands[1:]

            else:
                #output this command as unpacked
                out += struct.pack("<BBBB", commands[0]['instruction'], 0,0,0)
                for param in commands[0]['params']:
                    out += param
                commands = commands[1:]

        # ok. Last thing, we need the size of the finished
        # command list, for glCallList to use.
        out = struct.pack("<I", int(len(out)/4)) + out
        #done ^_^
        self.offset = 0
        return out

    # these are the individual commands, as defined in GBATEK, organized
    # in ascending order by command byte. For a full command reference, see
    # GBATEK, at http://nocash.emubase.de/gbatek.htm

    vtxs_triangle = 0
    vtxs_quad = 1
    vtxs_triangle_strip = 2
    vtxs_quadstrip = 3
    def begin_vtxs(self, format):
        cmd = self.command(0x40, [struct.pack("<I",format & 0x3)])
        self.cycles += 1
        return cmd

    def end_vtxs(self):
        pass #dummy command, real hardware does nothing, no point in outputting

    def vtx_16(self, x, y, z):
        # given vertex coordinates as floats, convert them into
        # 16bit fixed point numerals with 12bit fractional parts,
        # and pack them into two commands.

        # note: this command is ignoring overflow completely, do note that
        # values outside of the range (approx. -8 to 8) will produce strange
        # results.

        cmd = self.command(0x23, [
            struct.pack("<I",
            (int(x * 2**12) & 0xFFFF) |
            ((int(y * 2**12) & 0xFFFF) << 16)),
            struct.pack("<I",(int(z * 2**12) & 0xFFFF))
        ])
        self.cycles += 9
        return cmd

    def vtx_10(self, x, y, z):
        # same as vtx_10, but using 10bit coordinates with 6bit fractional bits;
        # this ends up being somewhat less accurate, but consumes one fewer
        # parameter in the list, and costs one fewer GPU cycle to draw.

        cmd = self.command(0x24, [
            struct.pack("<I",
            (int(x * 2**6) & 0x3FF) |
            ((int(y * 2**6) & 0x3FF) << 10) |
            ((int(z * 2**6) & 0x3FF) << 20))
        ])
        self.cycles += 8
        return cmd


    polygon_mode_modulation = 0
    polygon_mode_normal = 0
    polygon_mode_decal = 1
    polygon_mode_toon_highlight = 2
    polygon_mode_shadow = 3

    polygon_depth_less = 0
    polygon_depth_equal = 1
    def polygon_attr(self,
        light0=0, light1=0, light2=0, light3=0,
        mode=polygon_mode_modulation,
        front=1, back=0,
        new_depth=0,
        farplane_intersecting=1,
        dot_polygons=1,
        depth_test=polygon_depth_less,
        fog_enable=1,
        alpha=31,
        polygon_id=0):

        attr = ((light0 & 0x1 << 0) +
            ((light1 & 0x1) << 1) +
            ((light2 & 0x1) << 2) +
            ((light3 & 0x1) << 3) +
            ((mode & 0x3) << 4)  +
            ((back & 0x1) << 6) +
            ((front & 0x1) << 7) +
            ((new_depth & 0x1) << 11) + # for translucent polygons
            ((farplane_intersecting & 0x1) << 12) +
            ((depth_test & 0x1) << 14) +
            ((fog_enable & 0x1) << 15) +
            ((alpha & 0x1F) << 16) +    # 0-31
            ((polygon_id & 0x3F) << 24))

        cmd = self.command(0x29, [
            struct.pack("<I",attr)
        ])
        self.cycles += 1
        return cmd

    def color(self, red, green, blue, use256=False):
        if (use256):
            # DS colors are in 16bit mode (5 bits per value)
            red = int(red/8)
            blue = int(blue/8)
            green = int(green/8)
        cmd = self.command(0x20, [
            struct.pack("<I",
            (red & 0x1F) +
            ((green & 0x1F) << 5) +
            ((blue & 0x1F) << 10))
        ])
        self.cycles += 1
        return cmd

    def normal(self, x, y, z):
        cmd = self.command(0x21, [
            struct.pack("<I",
            (int((x*0.95) * 2**9) & 0x3FF) +
            ((int((y*0.95) * 2**9) & 0x3FF) << 10) +
            ((int((z*0.95) * 2**9) & 0x3FF) << 20))
        ])
        self.cycles += 9 # This is assuming just ONE light is turned on
        return cmd

    def dif_amb(self, diffuse, ambient, setvertex=False, use256=False):
        if (use256):
            # DS colors are in 16bit mode (5 bits per value)
            diffuse = (
                int(diffuse[0]/8),
                int(diffuse[1]/8),
                int(diffuse[2]/8),
            )
            ambient = (
                int(ambient[0]/8),
                int(ambient[1]/8),
                int(ambient[2]/8),
            )
        cmd = self.command(0x30, [
            struct.pack("<I",
            (diffuse[0] & 0x1F) +
            ((diffuse[1] & 0x1F) << 5) +
            ((diffuse[2] & 0x1F) << 10) +
            ((setvertex & 0x1) << 15) +
            ((ambient[0] & 0x1F) << 16) +
            ((ambient[1] & 0x1F) << 21) +
            ((ambient[2] & 0x1F) << 26))
        ])
        self.cycles += 4
        return cmd

    def spe_emi(self, specular, emit, use_specular_table=False, use256=False):
        if (use256):
            # DS colors are in 16bit mode (5 bits per value)
            specular = (
                int(specular[0]/8),
                int(specular[1]/8),
                int(specular[2]/8),
            )
            emit = (
                int(emit[0]/8),
                int(emit[1]/8),
                int(emit[2]/8),
            )
        cmd = self.command(0x31, [
            struct.pack("<I",
            (specular[0] & 0x1F) +
            ((specular[1] & 0x1F) << 5) +
            ((specular[2] & 0x1F) << 10) +
            ((use_specular_table & 0x1) << 15) +
            ((emit[0] & 0x1F) << 16) +
            ((emit[1] & 0x1F) << 21) +
            ((emit[2] & 0x1F) << 26))
        ])
        self.cycles += 4
        return cmd

    def push(self):
        self.command(0x11)
        self.cycles += 17

    def pop(self):
        self.command(0x12, [struct.pack("<I",0x1)])
        self.cycles += 36

    #note: expects a euclid.py matrix, any other format will not work
    def mtx_mult_4x4(self, matrix):
        self.command(0x18, [
                struct.pack("<i",to_fixed_point(matrix.a)), struct.pack("<i",to_fixed_point(matrix.b)), struct.pack("<i",to_fixed_point(matrix.c)), struct.pack("<i",to_fixed_point(matrix.d)),
                struct.pack("<i",to_fixed_point(matrix.e)), struct.pack("<i",to_fixed_point(matrix.f)), struct.pack("<i",to_fixed_point(matrix.g)), struct.pack("<i",to_fixed_point(matrix.h)),
                struct.pack("<i",to_fixed_point(matrix.i)), struct.pack("<i",to_fixed_point(matrix.j)), struct.pack("<i",to_fixed_point(matrix.k)), struct.pack("<i",to_fixed_point(matrix.l)),
                struct.pack("<i",to_fixed_point(matrix.m)), struct.pack("<i",to_fixed_point(matrix.n)), struct.pack("<i",to_fixed_point(matrix.o)), struct.pack("<i",to_fixed_point(matrix.p))
            ])
        self.cycles += 35

    def mtx_scale(self, sx, sy, sz):
        self.command(0x1B, [
                struct.pack("<i", to_fixed_point(sx)),
                struct.pack("<i", to_fixed_point(sy)),
                struct.pack("<i", to_fixed_point(sz))
            ])
        self.cycles += 22

    def texcoord(self, u, v):
        self.command(0x22, [
            struct.pack("<I",
            (int(u * 2**4) & 0xFFFF) |
            ((int(v * 2**4) & 0xFFFF) << 16))])
        self.cycles += 1

    def teximage_param(self, offset, width, height, format = 0, palette_transparency = 0, transform_mode = 0, u_repeat = 1, v_repeat = 1, u_flip = 0, v_flip = 0):
        #texture width/height is coded as Size = (8 << N). Thus, the range is 8..1024 (field size is 3 bits) and only N gets encoded, so we
        #need to convert incoming normal textures to this notation. (ie, 1024 would get written out as 7, since 1024 == (8 << 7))
        width_index = 0
        while width > 8:
            width = width >> 1
            width_index+=1;
        height_index = 0
        while height > 8:
            height = height >> 1
            height_index+=1;

        attr = (
            (int(offset / 8) & 0xFFFF) +
            ((u_repeat & 0x1) << 16) +
            ((v_repeat & 0x1) << 17) +
            ((u_flip & 0x1) << 18) +
            ((v_flip & 0x1) << 19) +
            ((width_index & 0x7) << 20) +
            ((height_index & 0x7) << 23) +
            ((format & 0x7) << 26) +
            ((palette_transparency & 0x1) << 29) +
            ((transform_mode & 0x3) << 30))
        cmd = self.command(0x2A, [
            struct.pack("<I",attr)])
        self.cycles += 1
        return cmd


    def texpllt_base(self, offset, texture_format):
        if texture_format == 2: # 4-color palette
            offset = offset >> 8
        else:
            offset = offset >> 16

        cmd = self.command(0x2B, [
            struct.pack("<I", (offset & 0xFFF))])
        self.cycles += 1
        return cmd
