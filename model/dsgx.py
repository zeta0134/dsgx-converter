"""Converter to and from DSGX files.

The Writer takes a Model instance and writes a DSGX file. DSGX is a RIFF-like
format, with the main difference being that the size of each chunk is in four
byte words instead of bytes. This is because the target platform is ARM, which
has issues reading incorrectly aligned data. All chunks are padded to four byte
alignment, elimintating the possibility of unaligned data without the need for
complex padding rules.
"""

import logging, struct
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

def to_fixed_point(float_value, fraction=12):
    return int(float_value * pow(2, fraction))

@reconcile(to_fixed_point)
def toFixed(float_value, fraction=12):
        return int(float_value * pow(2,fraction))

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

@reconcile(wrap_chunk)
def add_chunk_header(name, data):
    assert(len(name) == 4, "Cannot write chunk: %s, wrong size for header!" % name)
    name = [c.encode('ascii') for c in name]

    chunk = []

    #write the name as a non-null terminated 4-byte sequence
    chunk.append(struct.pack("<cccc", name[0], name[1], name[2], name[3]))

    #write out the length of data, in WORDS. (4-bytes per word)
    length = len(data)
    padding = 0
    if length % 4 != 0:
        padding = 4 - (length % 4)
        length = length + padding
    chunk.append(struct.pack("<I", int(length / 4)))

    #write out the chunk data
    chunk.append(data)

    # write out any padding bytes needed to word-align this data
    chunk.append(struct.pack("<" + "x" * padding))

    log.debug("Generated Chunk: %s", name)
    log.debug("Length: %d", int(length / 4))

    return b"".join(chunk)

def to_dsgx_string(string):
    """Convert string to a 32 byte null terminated C string byte string."""
    string = "" if string == None else string
    return struct.pack("<31sx", string.encode('ascii'))

@reconcile(to_dsgx_string)
def dsgx_string(str):
    if str == None:
        str = ""
    #DSGX strings are all, for sanity and word alignment, 32 characters long exactly, and null-terminated.
    #this means that any longer strings need to be truncated, and any shorter strings need to be
    #padded with 0 bytes in the output.
    output = bytes()
    for i in range(31):
        if i >= len(str):
            output += struct.pack("<x")
        else:
            output += struct.pack("<c",str[i].encode('ascii'))
    #force null terminattion
    output += struct.pack("<x")

    return output

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
        return None
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
        return None

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

class Writer:
    def face_attributes(self, gx, face, model):
        #write out per-polygon lighting and texture data, but only when that
        #data is different from the previous polygon
        log.debug("Switching to mtl: %s", face.material)
        if model.materials[face.material].texture != None:
            log.debug("Material has texture! Writing texture info out now.")
            texture_name = model.materials[face.material].texture
            if not texture_name in self.texture_offsets:
                self.texture_offsets[texture_name] = []
            self.texture_offsets[texture_name].append(gx.offset + 1)

            size = model.materials[face.material].texture_size
            gx.teximage_param(256 * 1024, size[0], size[1], 7)
            gx.texpllt_base(0, 0) # 0 for the offset and format; this will
                                  # be filled in by the engine during asset
                                  # loading.

        else:
            log.debug("Material has no texture; outputting dummy teximage to clear state")
            gx.teximage_param(0, 0, 0, 0)

        #polygon attributes for this material
        flags = parse_material_flags(face.material)
        if flags == None:
            gx.polygon_attr(light0=1, light1=1, light2=1, light3=1)
            pass
        else:
            log.debug("Encountered special case material!")
            polygon_alpha = 31
            if "alpha" in flags:
                polygon_alpha = int(flags["alpha"])
                log.debug("Custom alpha: %d", polygon_alpha)
            poly_id = 0
            if "id" in flags:
                poly_id = int(flags["id"])
                log.debug("Custom ID: %d", poly_id)
            gx.polygon_attr(light0=1, light1=1, light2=1, light3=1, alpha=polygon_alpha, polygon_id=poly_id)


        gx.dif_amb(
            (
                model.materials[face.material].diffuse[0] * 255,
                model.materials[face.material].diffuse[1] * 255,
                model.materials[face.material].diffuse[2] * 255), #diffuse
            (
                model.materials[face.material].ambient[0] * 255,
                model.materials[face.material].ambient[1] * 255,
                model.materials[face.material].ambient[2] * 255), #ambient
            False, #setVertexColor (not sure)
            True # use256
        )

        gx.spe_emi(
            (
                model.materials[face.material].specular[0] * 255,
                model.materials[face.material].specular[1] * 255,
                model.materials[face.material].specular[2] * 255), #specular
            (
                model.materials[face.material].emit[0] * 255,
                model.materials[face.material].emit[1] * 255,
                model.materials[face.material].emit[2] * 255), #emit
            False, #useSpecularTable
            True # use256
        )

    def output_vertex(self, gx, point, normal, model, face, vtx10=False):
        # point normal
        # p_normal = model.ActiveMesh().point_normal(point)
        if face.smooth_shading:
            if normal == None:
                log.warn("Problem: no normal for this point!", face.vertices)
            else:
                gx.normal(
                    normal[0],
                    normal[1],
                    normal[2],
                )
        # location
        location = model.ActiveMesh().vertices[point].location
        if vtx10:
            gx.vtx_10(
                location.x * self.scale_factor,
                location.y * self.scale_factor,
                location.z * self.scale_factor
            )
        else:
            gx.vtx_16(
                location.x * self.scale_factor,
                location.y * self.scale_factor,
                location.z * self.scale_factor
            )

    def determineScaleFactor(self, model):
        scale_factor = 1.0
        bb = model.bounding_box()
        largest_coordinate = max(abs(bb["wx"]), abs(bb["wy"]), abs(bb["wz"]))

        if largest_coordinate > 7.9:
            scale_factor = 7.9 / largest_coordinate
        return scale_factor

    def setup_sane_defaults(self, gx):
        # todo: figure out light offsets, if we ever want to have
        # dynamic scene lights and stuff with vertex colors
        gx.color(64, 64, 64, True) #use256 mode
        gx.polygon_attr(light0=1, light1=1, light2=1, light3=1)

        # default material, if no other material gets specified
        gx.dif_amb(
            (192,192,192), # diffuse
            (32,32,32),    # ambient fanciness
            False,         # setVertexColor (not sure)
            True           # use256
        )

    def start_polygon_list(self, gx, points_per_polygon):
        if (points_per_polygon == 3):
            gx.begin_vtxs(gx.vtxs_triangle)
        if (points_per_polygon == 4):
            gx.begin_vtxs(gx.vtxs_quad)

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
                self.start_polygon_list(gx, polytype)

                for face in model.ActiveMesh().polygons:
                    if (face.vertexGroup() == group and not face.isMixed() and
                            len(face.vertices) == polytype):
                        if current_material != face.material:
                            current_material = face.material
                            self.face_attributes(gx, face, model)
                            # on material edges, we need to start a new list
                            self.start_polygon_list(gx, polytype)
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
                            self.output_vertex(gx, face.vertices[p], face.vertex_normals[p], model, face, vtx10)
            gx.pop()

    def process_polygroup_faces(self, gx, model, vtx10=False):
        # now process mixed faces; similar, but we need to switch matricies *per point* rather than per face
        current_material = None
        for polytype in range(3,5):
            self.start_polygon_list(gx, polytype)
            for face in model.ActiveMesh().polygons:
                if len(face.vertices) == polytype and face.isMixed():
                    if current_material != face.material:
                        current_material = face.material
                        self.face_attributes(gx, face, model)
                        # on material edges, we need to start a new list
                        self.start_polygon_list(gx, polytype)
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
                        self.output_vertex(gx, point_index, face.vertex_normals[p], model, face, vtx10)
                        gx.pop()

    def output_active_bounding_sphere(self, fp, model):
        bsph = bytes()
        bsph += dsgx_string(model.active_mesh)
        sphere = model.bounding_sphere()
        bsph += struct.pack("<iiii", toFixed(sphere[0].x), toFixed(sphere[0].z), toFixed(sphere[0].y * -1), toFixed(sphere[1]))
        log.debug("Bounding Sphere:")
        log.debug("X: %f", sphere[0].x)
        log.debug("Y: %f", sphere[0].y)
        log.debug("Z: %f", sphere[0].z)
        log.debug("Radius: %f", sphere[1])
        fp.write(add_chunk_header("BSPH", bsph))

    def output_active_mesh(self, fp, model, vtx10=False):
        gx = Emitter()

        self.setup_sane_defaults(gx)

        self.group_offsets = {}
        self.texture_offsets = {}

        self.scale_factor = self.determineScaleFactor(model)

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

        fp.write(add_chunk_header("DSGX", dsgx_string(model.active_mesh) + gx.write()))
        self.output_active_bounding_sphere(fp, model)

        #output the cull-cost for the object
        log.debug("Cycles to Draw %s: %d", model.active_mesh, gx.cycles)
        fp.write(add_chunk_header("COST", dsgx_string(model.active_mesh) +
            struct.pack("<II", model.max_cull_polys(), gx.cycles)))

    def output_active_bones(self, fp, model):
        if not model.animations:
            return
        #matrix offsets for each bone
        bone = bytes()
        bone += dsgx_string(model.active_mesh)
        some_animation = model.animations[next(iter(model.animations.keys()))]
        bone += struct.pack("<I", len(some_animation.nodes.keys())) #number of bones in the file
        for node_name in sorted(some_animation.nodes.keys()):
            if node_name != "default":
                bone += dsgx_string(node_name) #name of this bone
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
        fp.write(add_chunk_header("BONE", bone))

    def output_active_textures(self, fp, model):
        #texparam offsets for each texture
        txtr = bytes()
        txtr += dsgx_string(model.active_mesh)
        txtr += struct.pack("<I", len(self.texture_offsets))
        log.debug("Total number of textures: %d", len(self.texture_offsets))
        for texture in sorted(self.texture_offsets):
            txtr += dsgx_string(texture) #name of this texture

            txtr += struct.pack("<I", len(self.texture_offsets[texture])) #number of references to this texture in the dsgx file

            #debug!
            log.debug("Writing texture data for: %s", texture)
            log.debug("Number of references: %d", len(self.texture_offsets[texture]))

            for offset in self.texture_offsets[texture]:
                txtr += struct.pack("<I", offset)
        fp.write(add_chunk_header("TXTR", txtr))

    def output_animations(self, fp, model):
        #animation data!
        for animation in model.animations:
            bani = bytes()
            bani += dsgx_string(animation)
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
                        bani += struct.pack("<iiii", toFixed(matrix.a), toFixed(matrix.b), toFixed(matrix.c), toFixed(matrix.d))
                        bani += struct.pack("<iiii", toFixed(matrix.e), toFixed(matrix.f), toFixed(matrix.g), toFixed(matrix.h))
                        bani += struct.pack("<iiii", toFixed(matrix.i), toFixed(matrix.j), toFixed(matrix.k), toFixed(matrix.l))
                        bani += struct.pack("<iiii", toFixed(matrix.m), toFixed(matrix.n), toFixed(matrix.o), toFixed(matrix.p))
                        count = count + 1
            fp.write(add_chunk_header("BANI", bani))
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
        return self.offset

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

        self.command(0x29, [
            struct.pack("<I",attr)
        ])
        self.cycles += 1

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
        self.command(0x30, [
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
        self.command(0x31, [
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

    def push(self):
        self.command(0x11)
        self.cycles += 17

    def pop(self):
        self.command(0x12, [struct.pack("<I",0x1)])
        self.cycles += 36

    #note: expects a euclid.py matrix, any other format will not work
    def mtx_mult_4x4(self, matrix):
        self.command(0x18, [
                struct.pack("<i",toFixed(matrix.a)), struct.pack("<i",toFixed(matrix.b)), struct.pack("<i",toFixed(matrix.c)), struct.pack("<i",toFixed(matrix.d)),
                struct.pack("<i",toFixed(matrix.e)), struct.pack("<i",toFixed(matrix.f)), struct.pack("<i",toFixed(matrix.g)), struct.pack("<i",toFixed(matrix.h)),
                struct.pack("<i",toFixed(matrix.i)), struct.pack("<i",toFixed(matrix.j)), struct.pack("<i",toFixed(matrix.k)), struct.pack("<i",toFixed(matrix.l)),
                struct.pack("<i",toFixed(matrix.m)), struct.pack("<i",toFixed(matrix.n)), struct.pack("<i",toFixed(matrix.o)), struct.pack("<i",toFixed(matrix.p))
            ])
        self.cycles += 35

    def mtx_scale(self, sx, sy, sz):
        self.command(0x1B, [
                struct.pack("<i", toFixed(sx)),
                struct.pack("<i", toFixed(sy)),
                struct.pack("<i", toFixed(sz))
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
        self.command(0x2A, [
            struct.pack("<I",attr)])
        self.cycles += 1


    def texpllt_base(self, offset, texture_format):
        if texture_format == 2: # 4-color palette
            offset = offset >> 8
        else:
            offset = offset >> 16

        self.command(0x2B, [
            struct.pack("<I", (offset & 0xFFF))])
        self.cycles += 1
