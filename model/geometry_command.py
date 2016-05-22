"""Implements the packing and generation of NDS graphics commands.

Not all commands are implemented. The reference used for all commands can be
found at http://problemkaputt.de/gbatek.htm#ds3dvideo .
"""

import struct
import euclid3 as euclid

_24bit_to_16bit = lambda components: _scale_components(components, 1 / 8, int)

def _command(command, parameters=None, tag=None):
    """Wrap up a command byte, its parameters, and an optional tag in a dict.

    The command byte should be the command to be passed into the geometry FIFO.

    The parameters are a list of all the arguments for the specified command.
    There is no validation as to whether the required number of arguments lines
    up with the number of arguments provided.

    The tag is a marker for use within the converter to identify the structures
    of origin the command was derived from. This is used to keep track of which
    matrices belong to which bones and which texture commands use what textures,
    among other things.
    """
    parameters = parameters if parameters else []
    if tag:
        return dict(instruction=command, params=parameters, tag=tag)
    return dict(instruction=command, params=parameters)

def _pack_bits(*bit_value_pairs):
    """Package valuse into a single integer given a description of bit fields.

    The two valid formats for a bit value pair are:
       (bit, value)
       ((low_bit, high_bit), value)
    The value provided is masked and shifted to fit inside the provided bit
    range, inclusive. Multiple pairs will all be packed into a single integer in
    the order they are listed.

    Overlapping bits are not explicitly checked for; overlapped bits will not be
    cleared before bitwise or-ing the new value on top of it.
    """
    packed_bits = 0
    for pair in bit_value_pairs:
        key, value = pair
        lower, upper = (key, key) if isinstance(key, int) else key
        bit_count = upper - lower + 1
        mask = (bit_count << bit_count) -1
        packed_bits |= (value & mask) << lower
    return packed_bits

def _pack_fixed_point_matrix_componentwise(matrix):
    """Convert a matrix to a row vector of binary packed fixed point values.

    The matrix is converted in row major order.
    """
    # matrix.transposed must be used because normal iteration yields a column
    # major result.
    return [struct.pack("< i", _to_fixed_point(element))
        for element in matrix.transposed()]

def _scale_components(components, constant, cast=None):
    """Scale all elements of components with an optional cast."""
    cast = cast if cast else lambda x: x
    return [cast(component * constant) for component in components]

def _texture_size_shift(size):
    """Convert size to the format expected by TEXIMAGE_PARAM.

    Texture sizes are always powers of two, and are specified to the hardware as
    8 << N, where N is the value passed to the TEXIMAGE_PARAM command.
    This method is used for both the S and T dimensions of a texture.

    http://problemkaputt.de/gbatek.htm#ds3dtextureattributes
    """
    shift = 0
    while 8 < size:
        size >>= 1
        shift += 1;
    return shift

def _to_fixed_point(float_value, fraction=12):
    """Convert a floating point value to a fixed point integer.

    The number specified for the fraction value is the number of fractional bits
    for the resulting integer.
    """
    return int(float_value * 2 ** fraction)

def begin_vtxs(primitive_type):
    return _command(0x40, [struct.pack("< I", _pack_bits(
        ((0, 1), primitive_type)))])

def color(red, green, blue, use_24bit=False):
    change_bitdepth = _24bit_to_16bit if use_24bit else lambda x: x
    red, green, blue = change_bitdepth([red, green, blue])
    return _command(0x20, [struct.pack("< I", _pack_bits(
        ((0, 4), red),
        ((5, 9), green),
        ((10, 14), blue)))])

def dif_amb(diffuse, ambient, setvertex=False, use_24bit=False):
    change_bitdepth = _24bit_to_16bit if use_24bit else lambda x: x
    diffuse = change_bitdepth(diffuse)
    ambient = change_bitdepth(ambient)
    return _command(0x30, [struct.pack("< I", _pack_bits(
        ((0, 4), diffuse[0]),
        ((5, 9), diffuse[1]),
        ((10, 14), diffuse[2]),
        (15, setvertex),
        ((16, 20), ambient[0]),
        ((21, 25), ambient[1]),
        ((26, 30), ambient[2])))])

def mtx_mult_4x4(matrix, tag=None):
    return _command(0x18, _pack_fixed_point_matrix_componentwise(matrix),
        tag=tag)

def mtx_scale(sx, sy, sz):
    return _command(0x1B, [struct.pack("< i", _to_fixed_point(axis))
        for axis in (sx, sy, sz)])

def normal(x, y, z):
    to_fixed_9 = lambda x: _to_fixed_point(x * 0.95, fraction=9) & 0x3FF
    return _command(0x21, [struct.pack("< I", _pack_bits(
        ((0, 9), to_fixed_9(x)),
        ((10, 19), to_fixed_9(y)),
        ((20, 29), to_fixed_9(z))))])

class PolygonAttr:
    class Mode:
        MODULATION = 0
        DECAL = 1
        TOON = 2
        SHADOW = 3
    class DepthTest:
        LESS = 0
        EQUAL = 1

def polygon_attr(light0=0, light1=0, light2=0, light3=0,
    mode=PolygonAttr.Mode.MODULATION, front=1, back=0, new_depth=0,
    farplane_intersecting=1, dot_polygons=1,
    depth_test=PolygonAttr.DepthTest.LESS, fog_enable=1, alpha=31,
    polygon_id=0):
    return _command(0x29, [struct.pack("< I", _pack_bits(
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
        ((24, 29), polygon_id)))])

def pop():
    return _command(0x12, [struct.pack("< I", 1)])

def push():
    return _command(0x11)

def spe_emi(specular, emit, use_specular_table=False, use_24bit=False):
    change_bitdepth = _24bit_to_16bit if use_24bit else lambda x: x
    specular = change_bitdepth(specular)
    emit = change_bitdepth(emit)
    return _command(0x31, [struct.pack("< I", _pack_bits(
        ((0, 4), specular[0]),
        ((5, 9), specular[1]),
        ((10, 14), specular[2]),
        (15, use_specular_table),
        ((16, 20), emit[0]),
        ((21, 25), emit[1]),
        ((26, 30), emit[2])))])

def texcoord(u, v):
    to_fixed_4 = lambda x: _to_fixed_point(x, fraction=4) & 0xFFFF
    return _command(0x22, [
        struct.pack("< I", _pack_bits(
            ((0, 15), to_fixed_4(u)),
            ((16, 31), to_fixed_4(v))))])

def teximage_param(width, height, offset=0, format=0, palette_transparency=0,
    transform_mode=0, u_repeat=1, v_repeat=1, u_flip=0, v_flip=0,
    texture_name=None):
    return _command(0x2A, [struct.pack("< I", _pack_bits(
        ((0, 15), int(offset / 8)),
        (16, u_repeat),
        (17, v_repeat),
        (18, u_flip),
        (19, v_flip),
        ((20, 22), _texture_size_shift(width)),
        ((23, 25), _texture_size_shift(height)),
        ((26, 28), format),
        (29, palette_transparency),
        ((30, 31), transform_mode)))], tag=texture_name)

def texpllt_base(offset, texture_format):
    FOUR_COLOR_PALETTE = 2
    shift = 8 if texture_format == FOUR_COLOR_PALETTE else 16
    return _command(0x2B, [struct.pack("< I", _pack_bits(
        ((0, 12), offset >> shift)))])

def vtx_10(x, y, z):
    # same as vtx_16, but using 10bit coordinates with 6bit fractional bits;
    # this ends up being somewhat less accurate, but consumes one fewer
    # parameter in the list, and costs one fewer GPU cycle to draw.
    to_fixed_6 = lambda x: _to_fixed_point(x, fraction=6) & 0x3FF
    return _command(0x24, [
        struct.pack("< I", _pack_bits(
            ((0, 9), to_fixed_6(x)),
            ((10, 19), to_fixed_6(y)),
            ((20, 29), to_fixed_6(z))))])

def vtx_16(x, y, z):
    # given vertex coordinates as floats, convert them into
    # 16bit fixed point numerals with 12bit fractional parts,
    # and pack them into two commands.

    # note: this command is ignoring overflow completely, do note that
    # values outside of the range (approx. -8 to 8) will produce strange
    # results.
    to_fixed_12 = lambda x: _to_fixed_point(x, fraction=12) & 0xFFFF
    return _command(0x23, [
        struct.pack("< I", _pack_bits(
            ((0, 15), to_fixed_12(x)),
            ((16, 31), to_fixed_12(y)))), struct.pack("< I", _pack_bits(
            ((0, 15), to_fixed_12(z))))])
