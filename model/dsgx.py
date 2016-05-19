"""Converter to and from DSGX files.

The Writer takes a Model instance and writes a DSGX file. DSGX is a RIFF-like
format, with the main difference being that the size of each chunk is in four
byte words instead of bytes. This is because the target platform is ARM, which
has issues reading incorrectly aligned data. All chunks are padded to four byte
alignment, elimintating the possibility of unaligned data without the need for
complex padding rules.
"""

import logging, struct
from collections import defaultdict
import euclid3 as euclid

log = logging.getLogger()
WORD_SIZE_BYTES = 4

def reconcile(new):
    """Ensure two functions return the same values given the same arugments."""
    def reconcile_decorator(old):
        def reconciler(*args, **kwargs):
            expected_result = old(*args, **kwargs)
            new_result = new(*args, **kwargs)
            assert expected_result == new_result, "unable to reconcile function results: %s returned %s but %s returned %s" % (old.__name__, repr(expected_result), new.__name__, repr(new_result))
            return expected_result
        return reconciler
    return reconcile_decorator

# from https://stackoverflow.com/a/10824420
def flatten(container):
    for i in container:
        if isinstance(i, (list, tuple)):
            for j in flatten(i):
                yield j
        else:
            yield i

def scale_components(components, constant, cast=None):
    if cast:
        return [cast(component * constant) for component in components]
    return [component * constant for component in components]

def to_fixed_point(float_value, fraction=12):
    return int(float_value * 2 ** fraction)

def wrap_chunk(name, data):
    """Convert data into the chunk format.

    Prepends the name of the chunk and the length of the payload in four byte
    words to data and appends zero padding to the end of the data to ensure the
    resulting chunk is an integer number of words long.

    name must be four characters long.
    """
    assert len(name) == 4, "invalid chunk name: %s is not four characters long" % name
    padding_size_bytes = padding_to(len(data), WORD_SIZE_BYTES)
    padded_payload_size_words = int((len(data) + padding_size_bytes) /
        WORD_SIZE_BYTES)
    chunk = struct.pack('< 4s I %ds %dx' % (len(data), padding_size_bytes),
        name.encode("ascii"), padded_payload_size_words, data)
    log.debug("Wrapped %s chunk with a %d word payload", name, padded_payload_size_words)
    return chunk

def padding_to(byte_count, alignment=WORD_SIZE_BYTES):
    """Calculate the number of bytes to pad byte_count bytes to alignment."""
    return alignment - (byte_count % alignment) if byte_count % alignment else 0

def to_dsgx_string(string):
    """Convert string to a 32 byte null terminated C string byte string."""
    string = "" if string == None else string
    return struct.pack("<31sx", string.encode('ascii'))

def parse_material_flags_new(material_name):
    """Extract the contents of flags embedded into the material_name.

    Flags are of the format:
       flag=value,flag=value|name
    or
       flag|name

    The pipe character indicates that flags are present, and the flags are comma
    separated. A flag without a value is interpreted as a boolean True.
    """
    if "|" not in material_name:
        return {}
    flags_string = material_name.split("|")[0]
    flag_parts = (flag.split("=") for flag in flags_string.split(","))
    flags = ((parts[0], (parts[1] if parts[1:] else True))
        for parts in flag_parts)
    return dict(flags)

@reconcile(parse_material_flags_new)
def parse_material_flags(material_name):
    #given the name of a material, see if there are any special flags
    #to extract. Material flags are in the format:
    #flag=value,flag=value|name
    #the presence of a pipe character indicates that they are flags to
    #parse, and the flags themselves are comma separated.

    sections = material_name.split("|")
    if len(sections) == 1:
        return {}

    flags = {}
    #split the separate flags on ","
    for flag in sections[0].split(","):
        #if a flag has a value, it will be preceeded by a "="
        parts = flag.split("=")
        flag_name = parts[0]
        if  len(parts) > 1:
            flags[flag_name] = parts[1]
        else:
            flags[flag_name] = True
    return flags

def command(command, parameters=None):
    parameters = parameters if parameters else []
    return dict(instruction=command, params=parameters)

def texture_size_shift(size):
    shift = 0
    while 8 < size:
        size >>= 1
        shift += 1;
    return shift

def pack_bits(*bit_value_pairs):
    packed_bits = 0
    for pair in bit_value_pairs:
        key, value = pair
        lower, upper = (key, key) if isinstance(key, int) else key
        bit_count = upper - lower + 1
        mask = (bit_count << bit_count) -1
        packed_bits |= (value & mask) << lower
    return packed_bits

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

def generate_texture_attributes(gx, texture_name, material, texture_offsets_list):
    DEFAULT_OFFSET = 256 * 1024
    DIRECT_TEXTURE = 7
    # TODO: This needs to be accounted for eventually once the gx refactoring is
    # done - i.e. once it is removed entirely
    # texture_offsets_list[texture_name].append(gx.offset + 1)
    width, height = material.texture_size
    # Since the location and format of the texture will only be known at
    # runtime, use zero for the offset and format. It will be filled in by the
    # engine during asset loading.
    return [teximage_param(width, height, format=DIRECT_TEXTURE,
        offset=DEFAULT_OFFSET), texpllt_base(0, 0)]

@reconcile(generate_texture_attributes)
def write_texture_attributes(gx, texture_name, material, texture_offsets_list):
    texture_offsets_list[texture_name].append(gx.offset + 1)

    size = material.texture_size
    return [gx.teximage_param(256 * 1024, size[0], size[1], 7),
        gx.texpllt_base(0, 0)] # 0 for the offset and format; this will
                               # be filled in by the engine during asset
                               # loading.

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

_24bit_to_16bit = lambda components: scale_components(components, 1 / 8, int)

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

CLEAR_TEXTURE_PARAMETERS = teximage_param(0, 0, 0, 0)

def generate_face_attributes(gx, face, model, texture_offsets_list):
    material = model.materials[face.material]
    flags = parse_material_flags(face.material)
    scale = lambda components: scale_components(components, 255)

    texture_attributes = (generate_texture_attributes(gx, material.texture,
        material, texture_offsets_list) if material.texture else
        CLEAR_TEXTURE_PARAMETERS)
    polygon_attributes = polygon_attr(light0=1, light1=1, light2=1, light3=1,
        alpha=int(flags.get("alpha", 31)), polygon_id=int(flags.get("id", 0)))
    material_properties = (dif_amb(scale(material.diffuse),
        scale(material.ambient), use256=True), spe_emi(scale(material.specular),
        scale(material.emit), use256=True))
    return list(flatten([texture_attributes,  polygon_attributes,
        material_properties]))

@reconcile(generate_face_attributes)
def write_face_attributes(gx, face, model, texture_offsets_list):
    #write out material and texture data for this polygon
    log.debug("Writing material: %s", face.material)
    gx_commands = []
    material = model.materials[face.material]
    if material.texture != None:
        log.debug("%s is textured! Writing texture info out now.", face.material)
        texture_name = model.materials[face.material].texture
        gx_commands.extend(write_texture_attributes(gx, texture_name, material, texture_offsets_list))
    else:
        log.debug("%s has no texture; outputting dummy teximage to clear state.", face.material)
        gx_commands.append(gx.teximage_param(0, 0, 0, 0))

    #polygon attributes for this material
    flags = parse_material_flags(face.material)
    if flags:
        log.debug("Encountered special case material!")
        polygon_alpha = 31
        if "alpha" in flags:
            polygon_alpha = int(flags["alpha"])
            log.debug("Custom alpha: %d", polygon_alpha)
        poly_id = 0
        if "id" in flags:
            poly_id = int(flags["id"])
            log.debug("Custom ID: %d", poly_id)
        gx_commands.append(gx.polygon_attr(light0=1, light1=1, light2=1, light3=1, alpha=polygon_alpha, polygon_id=poly_id))
    else:
        gx_commands.append(gx.polygon_attr(light0=1, light1=1, light2=1, light3=1))

    gx_commands.append(gx.dif_amb(
        [component * 255 for component in material.diffuse],
        [component * 255 for component in material.ambient],
        False, #setVertexColor (not sure)
        True # use256
    ))

    gx_commands.append(gx.spe_emi(
        [component * 255 for component in material.specular],
        [component * 255 for component in material.emit],
        False, #useSpecularTable
        True # use256
    ))
    return gx_commands

def write_normal(gx, normal):
    if normal == None:
        log.warn("Problem: no normal for this point!", face.vertices)
    else:
        gx.normal(*normal)

def write_vertex(gx, location, scale_factor, vtx10=False):
    if vtx10:
        gx.vtx_10(location.x * scale_factor, location.y * scale_factor, location.z * scale_factor)
    else:
        gx.vtx_16(location.x * scale_factor, location.y * scale_factor, location.z * scale_factor)

def determine_scale_factor(model):
    scale_factor = 1.0
    bb = model.bounding_box()
    largest_coordinate = max(abs(bb["wx"]), abs(bb["wy"]), abs(bb["wz"]))

    if largest_coordinate > 7.9:
        scale_factor = 7.9 / largest_coordinate
    return scale_factor

def write_sane_defaults(gx):
    # todo: figure out light offsets, if we ever want to have
    # dynamic scene lights and stuff with vertex colors
    gx.color(64, 64, 64, True) #use256 mode
    gx.polygon_attr(light0=1, light1=1, light2=1, light3=1)

    # default material, if no other material gets specified
    default_diffuse_color = (192,192,192)
    default_ambient_color = (32,32,32)
    set_vertex_color = False
    use_256_colors = True
    gx.dif_amb(default_diffuse_color, default_ambient_color, set_vertex_color,
               use_256_colors)

def start_polygon_list(gx, points_per_polygon):
    if (points_per_polygon == 3):
        gx.begin_vtxs(gx.vtxs_triangle)
    if (points_per_polygon == 4):
        gx.begin_vtxs(gx.vtxs_quad)

class Writer:
    def process_monogroup_faces(self, gx, model, vtx10=False):
        #process faces that all belong to one vertex group (simple case)
        current_material = None
        for group in model.groups:
            gx.push()

            #store this transformation offset for later
            if group != "default":
                if not group in self.group_offsets:
                    self.group_offsets[group] = []
                self.group_offsets[group].append(gx.offset + 1) #skip over the command itself; we need a reference to the parameters

            #emit a default matrix for this group; this makes the T-pose work
            #if no animation is selected
            gx.mtx_mult_4x4(euclid.Matrix4())

            for polytype in range(3,5):
                start_polygon_list(gx, polytype)

                for face in model.ActiveMesh().polygons:
                    if (face.vertexGroup() == group and not face.isMixed() and
                            len(face.vertices) == polytype):
                        if current_material != face.material:
                            current_material = face.material
                            write_face_attributes(gx, face, model, self.texture_offsets)
                            # on material edges, we need to start a new list
                            start_polygon_list(gx, polytype)
                        if not face.smooth_shading:
                            gx.normal(face.face_normal[0], face.face_normal[1], face.face_normal[2])
                        for p in range(len(face.vertices)):
                            # uv coordinate
                            if model.materials[current_material].texture:
                                # two things here:
                                # 1. The DS has limited precision, and expects texture coordinates based on the size of the texture, so
                                #    we multiply the UV coordinates such that 0.0, 1.0 maps to 0.0, <texture size>
                                # 2. UV coordinates are typically specified relative to the bottom-left of the image, but the DS again
                                #    expects coordinates from the top-left, so we need to invert the V coordinate to compensate.
                                size = model.materials[face.material].texture_size
                                gx.texcoord(face.uvlist[p][0] * size[0], (1.0 - face.uvlist[p][1]) * size[1])
                            if face.smooth_shading:
                                write_normal(gx, face.vertex_normals[p])
                            vertex_location = model.ActiveMesh().vertices[face.vertices[p]].location
                            write_vertex(gx, vertex_location, self.scale_factor, vtx10)
            gx.pop()

    def process_polygroup_faces(self, gx, model, vtx10=False):
        # now process mixed faces; similar, but we need to switch matricies *per point* rather than per face
        current_material = None
        for polytype in range(3,5):
            start_polygon_list(gx, polytype)
            for face in model.ActiveMesh().polygons:
                if len(face.vertices) == polytype and face.isMixed():
                    if current_material != face.material:
                        current_material = face.material
                        write_face_attributes(gx, face, model, self.texture_offsets)
                        # on material edges, we need to start a new list
                        start_polygon_list(gx, polytype)
                    if not face.smooth_shading:
                        gx.normal(face.face_normal[0], face.face_normal[1], face.face_normal[2])
                    for p in range(len(face.vertices)):
                        point_index = face.vertices[p]
                        gx.push()

                        # store this transformation offset for later
                        group = model.ActiveMesh().vertices[point_index].group
                        if not group in self.group_offsets:
                            self.group_offsets[group] = []
                        # skip over the command itself; we need a reference to
                        # the parameters
                        self.group_offsets[group].append(gx.offset + 1)

                        gx.mtx_mult_4x4(euclid.Matrix4())

                        if face.smooth_shading:
                            write_normal(gx, face.vertex_normals[p])
                        vertex_location = model.ActiveMesh().vertices[point_index].location
                        write_vertex(gx, vertex_location, self.scale_factor, vtx10)
                        gx.pop()

    def output_active_bounding_sphere(self, fp, model):
        bsph = bytes()
        bsph += to_dsgx_string(model.active_mesh)
        sphere = model.bounding_sphere()
        bsph += struct.pack("<iiii", to_fixed_point(sphere[0].x), to_fixed_point(sphere[0].z), to_fixed_point(sphere[0].y * -1), to_fixed_point(sphere[1]))
        log.debug("Bounding Sphere:")
        log.debug("X: %f", sphere[0].x)
        log.debug("Y: %f", sphere[0].y)
        log.debug("Z: %f", sphere[0].z)
        log.debug("Radius: %f", sphere[1])
        fp.write(wrap_chunk("BSPH", bsph))

    def output_active_mesh(self, fp, model, vtx10=False):
        gx = Emitter()

        write_sane_defaults(gx)

        self.group_offsets = {}
        self.texture_offsets = defaultdict(list)

        self.scale_factor = determine_scale_factor(model)

        gx.push()
        gx.mtx_mult_4x4(model.global_matrix)

        if self.scale_factor != 1.0:
            inverse_scale = 1 / self.scale_factor
            gx.mtx_scale(inverse_scale, inverse_scale, inverse_scale)

        log.debug("Global Matrix: ")
        log.debug(model.global_matrix)


        self.process_monogroup_faces(gx, model, vtx10)
        self.process_polygroup_faces(gx, model, vtx10)

        gx.pop() # mtx scale

        fp.write(wrap_chunk("DSGX", to_dsgx_string(model.active_mesh) + gx.write()))
        self.output_active_bounding_sphere(fp, model)

        #output the cull-cost for the object
        log.debug("Cycles to Draw %s: %d", model.active_mesh, gx.cycles)
        fp.write(wrap_chunk("COST", to_dsgx_string(model.active_mesh) +
            struct.pack("<II", model.max_cull_polys(), gx.cycles)))

    def output_active_bones(self, fp, model):
        if not model.animations:
            return
        #matrix offsets for each bone
        bone = bytes()
        bone += to_dsgx_string(model.active_mesh)
        some_animation = model.animations[next(iter(model.animations.keys()))]
        bone += struct.pack("<I", len(some_animation.nodes.keys())) #number of bones in the file
        for node_name in sorted(some_animation.nodes.keys()):
            if node_name != "default":
                bone += to_dsgx_string(node_name) #name of this bone
                if node_name in self.group_offsets:
                    bone += struct.pack("<I", len(self.group_offsets[node_name])) #number of copies of this matrix in the dsgx file

                    #debug
                    log.debug("Writing bone data for: %s", node_name)
                    log.debug("Number of offsets: %d", len(self.group_offsets[node_name]))

                    for offset in self.group_offsets[node_name]:
                        log.debug("Offset: %d", offset)
                        bone += struct.pack("<I", offset)
                else:
                    # We need to output a length of 0, so this bone is simply
                    # passed over
                    log.debug("Skipping bone data for: %s", node_name)
                    log.debug("Number of offsets: 0")
                    bone += struct.pack("<I", 0)
        fp.write(wrap_chunk("BONE", bone))

    def output_active_textures(self, fp, model):
        #texparam offsets for each texture
        txtr = bytes()
        txtr += to_dsgx_string(model.active_mesh)
        txtr += struct.pack("<I", len(self.texture_offsets))
        log.debug("Total number of textures: %d", len(self.texture_offsets))
        for texture in sorted(self.texture_offsets):
            txtr += to_dsgx_string(texture) #name of this texture

            txtr += struct.pack("<I", len(self.texture_offsets[texture])) #number of references to this texture in the dsgx file

            #debug!
            log.debug("Writing texture data for: %s", texture)
            log.debug("Number of references: %d", len(self.texture_offsets[texture]))

            for offset in self.texture_offsets[texture]:
                txtr += struct.pack("<I", offset)
        fp.write(wrap_chunk("TXTR", txtr))

    def output_animations(self, fp, model):
        #animation data!
        for animation in model.animations:
            bani = bytes()
            bani += to_dsgx_string(animation)
            bani += struct.pack("<I", model.animations[animation].length)
            log.debug("Writing animation data: %s", animation)
            log.debug("Length in frames: %d", model.animations[animation].length)
            #here, we output bone data per frame of the animation, making
            #sure to use the same bone order as the BONE chunk
            count = 0
            for frame in range(model.animations[animation].length):
                for node_name in sorted(model.animations[animation].nodes.keys()):
                    if node_name != "default":
                        if frame == 1:
                            log.debug("Writing node: %s", node_name)
                        matrix = model.animations[animation].getTransform(node_name, frame)
                        #hoo boy
                        bani += struct.pack("<iiii", to_fixed_point(matrix.a), to_fixed_point(matrix.b), to_fixed_point(matrix.c), to_fixed_point(matrix.d))
                        bani += struct.pack("<iiii", to_fixed_point(matrix.e), to_fixed_point(matrix.f), to_fixed_point(matrix.g), to_fixed_point(matrix.h))
                        bani += struct.pack("<iiii", to_fixed_point(matrix.i), to_fixed_point(matrix.j), to_fixed_point(matrix.k), to_fixed_point(matrix.l))
                        bani += struct.pack("<iiii", to_fixed_point(matrix.m), to_fixed_point(matrix.n), to_fixed_point(matrix.o), to_fixed_point(matrix.p))
                        count = count + 1
            fp.write(wrap_chunk("BANI", bani))
            log.debug("Wrote %d matricies", count)

    def write(self, filename, model, vtx10=False):
        fp = open(filename, "wb")
        #first things first, output the main data
        for mesh_name in model.meshes:
            model.active_mesh = mesh_name
            self.output_active_mesh(fp, model, vtx10)
            self.output_active_bones(fp, model)
            self.output_active_textures(fp, model)

        self.output_animations(fp, model)

        fp.close()

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
        self.command(0x40, [struct.pack("<I",format & 0x3)])
        self.cycles += 1

    def end_vtxs(self):
        pass #dummy command, real hardware does nothing, no point in outputting

    def vtx_16(self, x, y, z):
        # given vertex coordinates as floats, convert them into
        # 16bit fixed point numerals with 12bit fractional parts,
        # and pack them into two commands.

        # note: this command is ignoring overflow completely, do note that
        # values outside of the range (approx. -8 to 8) will produce strange
        # results.

        self.command(0x23, [
            struct.pack("<I",
            (int(x * 2**12) & 0xFFFF) |
            ((int(y * 2**12) & 0xFFFF) << 16)),
            struct.pack("<I",(int(z * 2**12) & 0xFFFF))
        ])
        self.cycles += 9

    def vtx_10(self, x, y, z):
        # same as vtx_10, but using 10bit coordinates with 6bit fractional bits;
        # this ends up being somewhat less accurate, but consumes one fewer
        # parameter in the list, and costs one fewer GPU cycle to draw.

        self.command(0x24, [
            struct.pack("<I",
            (int(x * 2**6) & 0x3FF) |
            ((int(y * 2**6) & 0x3FF) << 10) |
            ((int(z * 2**6) & 0x3FF) << 20))
        ])
        self.cycles += 8


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
        self.command(0x20, [
            struct.pack("<I",
            (red & 0x1F) +
            ((green & 0x1F) << 5) +
            ((blue & 0x1F) << 10))
        ])
        self.cycles += 1

    def normal(self, x, y, z):
        self.command(0x21, [
            struct.pack("<I",
            (int((x*0.95) * 2**9) & 0x3FF) +
            ((int((y*0.95) * 2**9) & 0x3FF) << 10) +
            ((int((z*0.95) * 2**9) & 0x3FF) << 20))
        ])
        self.cycles += 9 # This is assuming just ONE light is turned on

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
