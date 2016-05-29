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

class PrimitiveType:
    SEPARATE_TRIANGLES = 0
    SEPAPATE_QUADRILATERALS = 1
    TRIANGLE_STRIPS = 2
    QUADRILATERAL_STRIPS = 3

def begin_vtxs(primitive_type):
    """Start a new list of vertices for the specified primitive_type.

    http://problemkaputt.de/gbatek.htm#ds3dpolygondefinitionsbyvertices
    """
    return _command(0x40, [struct.pack("< I", _pack_bits(
        ((0, 1), primitive_type)))])

def color(red, green, blue, use_24bit=False):
    """Directly set the vertex color for all following vertex commands.

    http://problemkaputt.de/gbatek.htm#ds3dpolygonattributes
    """
    change_bitdepth = _24bit_to_16bit if use_24bit else lambda x: x
    red, green, blue = change_bitdepth([red, green, blue])
    return _command(0x20, [struct.pack("< I", _pack_bits(
        ((0, 4), red),
        ((5, 9), green),
        ((10, 14), blue)))])

def dif_amb(diffuse, ambient, use_diffuse_as_vertex_color=False,
    use_24bit=False):
    """Set the diffuse and ambient reflection for all following vertex commands.

    http://problemkaputt.de/gbatek.htm#ds3dpolygonlightparameters
    """
    change_bitdepth = _24bit_to_16bit if use_24bit else lambda x: x
    diffuse = change_bitdepth(diffuse)
    ambient = change_bitdepth(ambient)
    return _command(0x30, [struct.pack("< I", _pack_bits(
        ((0, 4), diffuse[0]),
        ((5, 9), diffuse[1]),
        ((10, 14), diffuse[2]),
        (15, use_diffuse_as_vertex_color),
        ((16, 20), ambient[0]),
        ((21, 25), ambient[1]),
        ((26, 30), ambient[2])))])

def mtx_mult_4x4(matrix, tag=None):
    """Multiply the matrix at the top of the stack by the provided matrix.

    http://problemkaputt.de/gbatek.htm#ds3dmatrixloadmultiply
    """
    return _command(0x18, _pack_fixed_point_matrix_componentwise(matrix),
        tag=tag)

def mtx_scale(sx, sy, sz):
    """Multiply the matrix at the top of the stack by a scale matrix.

    http://problemkaputt.de/gbatek.htm#ds3dmatrixloadmultiply
    """
    return _command(0x1B, [struct.pack("< i", _to_fixed_point(axis))
        for axis in (sx, sy, sz)])

def normal(x, y, z, tag=None):
    """Calculate the vertex color based on lighting.

    http://problemkaputt.de/gbatek.htm#ds3dpolygonlightparameters
    """
    # Normals are typically represented as unit vectors, but the DS's normal
    # command is composed entirely of fractional bits. This means that a true
    # unit vector that faces directly along any of the axes would underflow,
    # resulting in incorrect lighting. To compensate, reduce the size of all
    # normal components slightly.
    to_fixed_9 = lambda x: _to_fixed_point(x * 0.95, fraction=9) & 0x3FF
    return _command(0x21, [struct.pack("< I", _pack_bits(
        ((0, 9), to_fixed_9(x)),
        ((10, 19), to_fixed_9(y)),
        ((20, 29), to_fixed_9(z))))], tag=tag)

class PolygonAttr:
    class DepthTest:
        LESS = 0
        EQUAL = 1
    class DotPolygons:
        HIDE = 0
        RENDER = 1
    class FarPlaneIntersecting:
        HIDE = 0
        RENDER_CLIPPED = 1
    class Fog:
        DISABLE = 0
        ENABLE = 1
    class Light:
        DISABLE = 0
        ENABLE = 1
    class Mode:
        MODULATION = 0
        DECAL = 1
        TOON = 2
        SHADOW = 3
    class Surface:
        HIDE = 0
        RENDER = 1
    class TranslucentDepth:
        KEEP_OLD = 0
        SET_NEW = 1

def polygon_attr(light0=PolygonAttr.Light.DISABLE,
    light1=PolygonAttr.Light.DISABLE, light2=PolygonAttr.Light.DISABLE,
    light3=PolygonAttr.Light.DISABLE, mode=PolygonAttr.Mode.MODULATION,
    front=PolygonAttr.Surface.RENDER, back=PolygonAttr.Surface.HIDE,
    new_depth=PolygonAttr.TranslucentDepth.KEEP_OLD,
    farplane_intersecting=PolygonAttr.FarPlaneIntersecting.RENDER_CLIPPED,
    dot_polygons=PolygonAttr.DotPolygons.RENDER,
    depth_test=PolygonAttr.DepthTest.LESS, fog_enable=PolygonAttr.Fog.ENABLE,
    alpha=31, polygon_id=0):
    """Set various attributes for the next BEGIN_VTXS command.

    http://problemkaputt.de/gbatek.htm#ds3dpolygonattributes
    """
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
    """Remove one matrix from the top of the matrix stack.

    http://problemkaputt.de/gbatek.htm#ds3dmatrixstack
    """
    return _command(0x12, [struct.pack("< I", 1)])

def push():
    """Add another matrix to the top of the matrix stack.

    http://problemkaputt.de/gbatek.htm#ds3dmatrixstack
    """
    return _command(0x11)

def spe_emi(specular, emit, use_specular_table=False, use_24bit=False):
    """Set the specular and emit reflection for all following vertex commands.

    http://problemkaputt.de/gbatek.htm#ds3dpolygonlightparameters
    """
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
    """Specifies the source texel in the current texture for the next vertex.

    http://problemkaputt.de/gbatek.htm#ds3dtextureattributes
    """
    to_fixed_4 = lambda x: _to_fixed_point(x, fraction=4) & 0xFFFF
    return _command(0x22, [
        struct.pack("< I", _pack_bits(
            ((0, 15), to_fixed_4(u)),
            ((16, 31), to_fixed_4(v))))])

class TeximageParam:
    class Flip:
        NO = 0
        YES = 1
    class Format:
        NO_TEXTURE = 0
        A3I5 = 1
        PALETTED_4_COLOR = 2
        PALETTED_16_COLOR = 3
        PALETTED_256_COLOR = 4
        COMPRESSED_4x4 = 5
        A5I3 = 6
        DIRECT = 7
    class Repeat:
        CLAMP = 0
        REPEAT = 1
    class Color0:
        DISPLAYED = 0
        TRANSPARENT = 1

def teximage_param(width, height, vram_offset=0,
    format=TeximageParam.Format.NO_TEXTURE,
    palette_transparency=TeximageParam.Color0.DISPLAYED, transform_mode=0,
    u_repeat=TeximageParam.Repeat.REPEAT, v_repeat=TeximageParam.Repeat.REPEAT,
    u_flip=TeximageParam.Flip.NO, v_flip=TeximageParam.Flip.NO,
    texture_name=None):
    """Specify which texture is used and how to interpret it.

    http://problemkaputt.de/gbatek.htm#ds3dtextureattributes
    """
    return _command(0x2A, [struct.pack("< I", _pack_bits(
        ((0, 15), int(vram_offset / 8)),
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
    """Set the palette offset for paletted textures.

    http://problemkaputt.de/gbatek.htm#ds3dtextureattributes
    """
    shift = 8 if texture_format == TeximageParam.Format.PALETTED_4_COLOR else 16
    return _command(0x2B, [struct.pack("< I", _pack_bits(
        ((0, 12), offset >> shift)))])

def vtx_10(x, y, z, tag=None):
    """Specify a vertex with 1.3.6 fixed point components.

    This is similar to vtx_16, but is less accurate in exchange for requiring
    one less argument word. This can result in significant savings in space and
    FIFO bandwidth.

    Overflow is not handled at all, so passing coordinates larger than +/-2 ** 3
    will wrap and produce graphical artifacts.

    http://problemkaputt.de/gbatek.htm#ds3dpolygondefinitionsbyvertices
    """
    to_fixed_6 = lambda x: _to_fixed_point(x, fraction=6) & 0x3FF
    return _command(0x24, [
        struct.pack("< I", _pack_bits(
            ((0, 9), to_fixed_6(x)),
            ((10, 19), to_fixed_6(y)),
            ((20, 29), to_fixed_6(z))))], tag=tag)

def vtx_16(x, y, z, tag=None):
    """Specify a vertex with 1.3.12 fixed point components.

    This vertex format requires two argument words, but has higher precision
    than the other vertex commands.

    Overflow is not handled at all, so passing coordinates larger than +/-2 ** 3
    will wrap and produce graphical artifacts.

    http://problemkaputt.de/gbatek.htm#ds3dpolygondefinitionsbyvertices
    """
    to_fixed_12 = lambda x: _to_fixed_point(x, fraction=12) & 0xFFFF
    return _command(0x23, [
        struct.pack("< I", _pack_bits(
            ((0, 15), to_fixed_12(x)),
            ((16, 31), to_fixed_12(y)))), struct.pack("< I", _pack_bits(
            ((0, 15), to_fixed_12(z))))], tag=tag)
