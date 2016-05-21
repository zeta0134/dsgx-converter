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
import model.geometry_command as gc
from model.geometry_command import to_fixed_point

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

def parse_material_flags(material_name):
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
    return [gc.teximage_param(width, height, format=DIRECT_TEXTURE,
        offset=DEFAULT_OFFSET), gc.texpllt_base(0, 0)]

@reconcile(generate_texture_attributes)
def write_texture_attributes(gx, texture_name, material, texture_offsets_list):
    texture_offsets_list[texture_name].append(gx.offset + 1)

    size = material.texture_size
    return [gx.teximage_param(256 * 1024, size[0], size[1], 7),
        gx.texpllt_base(0, 0)] # 0 for the offset and format; this will
                               # be filled in by the engine during asset
                               # loading.

CLEAR_TEXTURE_PARAMETERS = gc.teximage_param(0, 0, 0, 0)

def generate_face_attributes(gx, face, model, texture_offsets_list):
    material = model.materials[face.material]
    flags = parse_material_flags(face.material)
    scale = lambda components: gc.scale_components(components, 255)

    texture_attributes = (generate_texture_attributes(gx, material.texture,
        material, texture_offsets_list) if material.texture else
        CLEAR_TEXTURE_PARAMETERS)
    polygon_attributes = gc.polygon_attr(light0=1, light1=1, light2=1, light3=1,
        alpha=int(flags.get("alpha", 31)), polygon_id=int(flags.get("id", 0)))
    material_properties = (gc.dif_amb(scale(material.diffuse),
        scale(material.ambient), use256=True), gc.spe_emi(scale(material.specular),
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

def generate_normal(gx, normal_vector):
    return gc.normal(*normal_vector)

@reconcile(generate_normal)
def write_normal(gx, normal):
    if normal == None:
        log.warn("Problem: no normal for this point!", face.vertices)
    else:
        return gx.normal(*normal)

def generate_vertex(gx, location, scale_factor, vtx10=False):
    vtx = gc.vtx_10 if vtx10 else gc.vtx_16
    return vtx(location.x * scale_factor, location.y * scale_factor, location.z * scale_factor)

@reconcile(generate_vertex)
def write_vertex(gx, location, scale_factor, vtx10=False):
    if vtx10:
        return gx.vtx_10(location.x * scale_factor, location.y * scale_factor, location.z * scale_factor)
    else:
        return gx.vtx_16(location.x * scale_factor, location.y * scale_factor, location.z * scale_factor)

def determine_scale_factor_new(mesh):
    box = mesh.bounding_box()
    largest_coordinate = max(abs(box["wx"]), abs(box["wy"]), abs(box["wz"]))
    return 1.0 if largest_coordinate <= 7.9 else 7.9 / largest_coordinate

@reconcile(determine_scale_factor_new)
def determine_scale_factor(mesh):
    scale_factor = 1.0
    bb = mesh.bounding_box()
    largest_coordinate = max(abs(bb["wx"]), abs(bb["wy"]), abs(bb["wz"]))

    if largest_coordinate > 7.9:
        scale_factor = 7.9 / largest_coordinate
    return scale_factor

def generate_defaults(gx):
    # todo: figure out light offsets, if we ever want to have
    # dynamic scene lights and stuff with vertex colors
    # default material, if no other material gets specified
    default_diffuse_color = 192, 192, 192
    default_ambient_color = 32, 32, 32
    return [gc.color(64, 64, 64, use256=True),
        gc.polygon_attr(light0=1, light1=1, light2=1, light3=1),
        gc.dif_amb(default_diffuse_color, default_ambient_color, use256=True)]

@reconcile(generate_defaults)
def write_sane_defaults(gx):
    gx_commands = []  # TODO
    # todo: figure out light offsets, if we ever want to have
    # dynamic scene lights and stuff with vertex colors
    gx_commands.append(gx.color(64, 64, 64, True)) #use256 mode
    gx_commands.append(gx.polygon_attr(light0=1, light1=1, light2=1, light3=1))

    # default material, if no other material gets specified
    default_diffuse_color = (192,192,192)
    default_ambient_color = (32,32,32)
    set_vertex_color = False
    use_256_colors = True
    gx_commands.append(gx.dif_amb(default_diffuse_color, default_ambient_color,
        set_vertex_color, use_256_colors))
    return gx_commands

VTXS_TRIANGLE = 0
VTXS_QUAD = 1
def generate_polygon_list_start(gx, points_per_polygon):
    assert points_per_polygon in (3, 4), "Invalid number of points in polygon: %d" % points_per_polygon
    return gc.begin_vtxs(VTXS_TRIANGLE if points_per_polygon == 3 else VTXS_QUAD)

@reconcile(generate_polygon_list_start)
def start_polygon_list(gx, points_per_polygon):
    if (points_per_polygon == 3):
        return gx.begin_vtxs(gx.vtxs_triangle)
    if (points_per_polygon == 4):
        return gx.begin_vtxs(gx.vtxs_quad)

def process_monogroup_faces(gx, model, mesh, scale_factor, group_offsets, texture_offsets, vtx10=False):
    gx_commands = []
    #process faces that all belong to one vertex group (simple case)
    current_material = None
    for group in model.groups:
        gx_commands.append(gx.push())

        #store this transformation offset for later
        if group != "default":
            group_offsets[group].append(gx.offset + 1) #skip over the command itself; we need a reference to the parameters

        #emit a default matrix for this group; this makes the T-pose work
        #if no animation is selected
        gx_commands.append(gx.mtx_mult_4x4(euclid.Matrix4()))

        for polytype in range(3,5):
            gx_commands.append(start_polygon_list(gx, polytype))

            for face in mesh.polygons:
                if (face.vertexGroup() == group and not face.isMixed() and
                        len(face.vertices) == polytype):
                    if current_material != face.material:
                        current_material = face.material
                        gx_commands.append(write_face_attributes(gx, face, model, texture_offsets))
                        # on material edges, we need to start a new list
                        gx_commands.append(start_polygon_list(gx, polytype))
                    if not face.smooth_shading:
                        gx_commands.append(gx.normal(face.face_normal[0], face.face_normal[1], face.face_normal[2]))
                    for p in range(len(face.vertices)):
                        # uv coordinate
                        if model.materials[current_material].texture:
                            # two things here:
                            # 1. The DS has limited precision, and expects texture coordinates based on the size of the texture, so
                            #    we multiply the UV coordinates such that 0.0, 1.0 maps to 0.0, <texture size>
                            # 2. UV coordinates are typically specified relative to the bottom-left of the image, but the DS again
                            #    expects coordinates from the top-left, so we need to invert the V coordinate to compensate.
                            size = model.materials[face.material].texture_size
                            gx_commands.append(gx.texcoord(face.uvlist[p][0] * size[0], (1.0 - face.uvlist[p][1]) * size[1]))
                        if face.smooth_shading:
                            gx_commands.append(write_normal(gx, face.vertex_normals[p]))
                        vertex_location = mesh.vertices[face.vertices[p]].location
                        gx_commands.append(write_vertex(gx, vertex_location, scale_factor, vtx10))
        gx_commands.append(gx.pop())
    return list(flatten(gx_commands))

def process_polygroup_faces(gx, model, mesh, scale_factor, group_offsets, texture_offsets, vtx10=False):
    # now process mixed faces; similar, but we need to switch matricies *per point* rather than per face
    current_material = None
    for polytype in range(3,5):
        start_polygon_list(gx, polytype)
        for face in mesh.polygons:
            if len(face.vertices) == polytype and face.isMixed():
                if current_material != face.material:
                    current_material = face.material
                    write_face_attributes(gx, face, model, texture_offsets)
                    # on material edges, we need to start a new list
                    start_polygon_list(gx, polytype)
                if not face.smooth_shading:
                    gx.normal(face.face_normal[0], face.face_normal[1], face.face_normal[2])
                for p in range(len(face.vertices)):
                    point_index = face.vertices[p]
                    gx.push()

                    # store this transformation offset for later
                    group = mesh.vertices[point_index].group
                    if not group in group_offsets:
                        group_offsets[group] = []
                    # skip over the command itself; we need a reference to
                    # the parameters
                    group_offsets[group].append(gx.offset + 1)

                    gx.mtx_mult_4x4(euclid.Matrix4())

                    if face.smooth_shading:
                        write_normal(gx, face.vertex_normals[p])
                    vertex_location = mesh.vertices[point_index].location
                    write_vertex(gx, vertex_location, scale_factor, vtx10)
                    gx.pop()

def generate_bounding_sphere(_, mesh):
    sphere = mesh.bounding_sphere()
    log.debug("Bounding sphere of radius %f centered at (%f, %f, %f)",
        sphere[1], sphere[0].x, sphere[0].y, sphere[0].z)
    return wrap_chunk("BSPH", struct.pack("< 32s i i i i",
        to_dsgx_string(mesh.name), to_fixed_point(sphere[0].x),
        to_fixed_point(sphere[0].z), to_fixed_point(sphere[0].y * -1),
        to_fixed_point(sphere[1])))

@reconcile(generate_bounding_sphere)
def output_bounding_sphere(fp, mesh):
    bsph = bytes()
    bsph += to_dsgx_string(mesh.name)
    sphere = mesh.bounding_sphere()
    bsph += struct.pack("<iiii", to_fixed_point(sphere[0].x), to_fixed_point(sphere[0].z), to_fixed_point(sphere[0].y * -1), to_fixed_point(sphere[1]))
    log.debug("Bounding Sphere:")
    log.debug("X: %f", sphere[0].x)
    log.debug("Y: %f", sphere[0].y)
    log.debug("Z: %f", sphere[0].z)
    log.debug("Radius: %f", sphere[1])
    chunk = wrap_chunk("BSPH", bsph)
    fp.write(chunk)
    return chunk

def generate_mesh(fp, model, mesh, group_offsets, texture_offsets, vtx10=False):
    gx = gc.Emitter()

    dsgx_chunk = generate_dsgx(gx, model, mesh, group_offsets, texture_offsets, vtx10)
    # fp.write(dsgx_chunk)
    bsph_chunk = generate_bounding_sphere(None, mesh)

    #output the cull-cost for the object
    log.debug("Cycles to Draw %s: %d", mesh.name, gx.cycles)
    cost_chunk = wrap_chunk("COST", to_dsgx_string(mesh.name) +
        struct.pack("<II", mesh.max_cull_polys(), gx.cycles))
    # fp.write(cost_chunk)
    return [dsgx_chunk, bsph_chunk, cost_chunk]

def generate_dsgx(gx, model, mesh, group_offsets, texture_offsets, vtx10=False):
    gx_commands = []
    gx_commands.append(generate_defaults(None))
    # write_sane_defaults(gx)

    scale_factor = determine_scale_factor_new(mesh)

    gx_commands.append(gc.push())
    gx_commands.append(gc.mtx_mult_4x4(model.global_matrix))
    # gx.push()
    # gx.mtx_mult_4x4(model.global_matrix)

    if scale_factor != 1.0:
        inverse_scale = 1 / scale_factor
        gx_commands.append(gc.mtx_scale(inverse_scale, inverse_scale, inverse_scale))
        # gx.mtx_scale(inverse_scale, inverse_scale, inverse_scale)

    log.debug("Global Matrix: ")
    log.debug(model.global_matrix)

    gx_commands.append(process_monogroup_faces(gx, model, mesh, scale_factor, group_offsets, texture_offsets, vtx10))
    # process_monogroup_faces(gx, model, mesh, scale_factor, group_offsets, texture_offsets, vtx10)

    gx_commands.append(gc.pop())
    # gx.pop() # mtx scale

    # return wrap_chunk("DSGX", to_dsgx_string(mesh.name) + gx.write())
    return wrap_chunk("DSGX", to_dsgx_string(mesh.name) + generate_gl_call_list(list(flatten(gx_commands))))

def generate_gl_call_list(commands):
    call_list = []
    for command in commands:
        command_bytes = struct.pack("< B B B B", command["instruction"], 0, 0, 0)
        command_bytes += b"".join(command["params"])
        call_list.append(command_bytes)
    call_list = b"".join(call_list)
    return struct.pack("< I %ds" % len(call_list), int(len(call_list) / 4), call_list)

# @reconcile(generate_mesh)
def output_mesh(fp, model, mesh, group_offsets, texture_offsets, vtx10=False):
    # generate_mesh(None, model, mesh, group_offsets, texture_offsets, vtx10)
    gx = gc.Emitter()

    write_sane_defaults(gx)

    scale_factor = determine_scale_factor(mesh)

    gx.push()
    gx.mtx_mult_4x4(model.global_matrix)

    if scale_factor != 1.0:
        inverse_scale = 1 / scale_factor
        gx.mtx_scale(inverse_scale, inverse_scale, inverse_scale)

    log.debug("Global Matrix: ")
    log.debug(model.global_matrix)

    process_monogroup_faces(gx, model, mesh, scale_factor, group_offsets, texture_offsets, vtx10)
    # process_monogroup_faces(gx, model, mesh, scale_factor, group_offsets, texture_offsets, vtx10)

    gx.pop() # mtx scale

    dsgx_chunk = wrap_chunk("DSGX", to_dsgx_string(mesh.name) + gx.write())
    fp.write(dsgx_chunk)
    bsph_chunk = output_bounding_sphere(fp, mesh)

    #output the cull-cost for the object
    log.debug("Cycles to Draw %s: %d", mesh.name, gx.cycles)
    cost_chunk = wrap_chunk("COST", to_dsgx_string(mesh.name) +
        struct.pack("<II", mesh.max_cull_polys(), gx.cycles))
    fp.write(cost_chunk)
    return [dsgx_chunk, bsph_chunk, cost_chunk]

def output_bones(fp, model, mesh, group_offsets):
    if not model.animations:
        return
    #matrix offsets for each bone
    bone = bytes()
    bone += to_dsgx_string(mesh.name)
    some_animation = model.animations[next(iter(model.animations.keys()))]
    bone += struct.pack("<I", len(some_animation.nodes.keys())) #number of bones in the file
    for node_name in sorted(some_animation.nodes.keys()):
        if node_name != "default":
            bone += to_dsgx_string(node_name) #name of this bone
            if node_name in group_offsets:
                bone += struct.pack("<I", len(group_offsets[node_name])) #number of copies of this matrix in the dsgx file

                #debug
                log.debug("Writing bone data for: %s", node_name)
                log.debug("Number of offsets: %d", len(group_offsets[node_name]))

                for offset in group_offsets[node_name]:
                    log.debug("Offset: %d", offset)
                    bone += struct.pack("<I", offset)
            else:
                # We need to output a length of 0, so this bone is simply
                # passed over
                log.debug("Skipping bone data for: %s", node_name)
                log.debug("Number of offsets: 0")
                bone += struct.pack("<I", 0)
    fp.write(wrap_chunk("BONE", bone))

def output_textures(fp, model, mesh, texture_offsets):
    #texparam offsets for each texture
    txtr = bytes()
    txtr += to_dsgx_string(mesh.name)
    txtr += struct.pack("<I", len(texture_offsets))
    log.debug("Total number of textures: %d", len(texture_offsets))
    for texture in sorted(texture_offsets):
        txtr += to_dsgx_string(texture) #name of this texture

        txtr += struct.pack("<I", len(texture_offsets[texture])) #number of references to this texture in the dsgx file

        #debug!
        log.debug("Writing texture data for: %s", texture)
        log.debug("Number of references: %d", len(texture_offsets[texture]))

        for offset in texture_offsets[texture]:
            txtr += struct.pack("<I", offset)
    fp.write(wrap_chunk("TXTR", txtr))

def output_animations(fp, model):
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

class Writer:
    def write(self, filename, model, vtx10=False):
        fp = open(filename, "wb")
        #first things first, output the main data
        for mesh_name in model.meshes:
            mesh = model.meshes[mesh_name]
            group_offsets = defaultdict(list)
            texture_offsets = defaultdict(list)
            output_mesh(fp, model, mesh, group_offsets, texture_offsets, vtx10)
            output_bones(fp, model, mesh, group_offsets)
            output_textures(fp, model, mesh, texture_offsets)

        output_animations(fp, model)

        fp.close()
