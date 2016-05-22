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
from itertools import groupby
from operator import methodcaller, attrgetter

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
    return alignment - byte_count % alignment if byte_count % alignment else 0

def to_dsgx_string(string):
    """Convert string to a 32 byte null terminated C string byte string."""
    string = string if string else ""
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

def generate_texture_attributes(material):
    DIRECT_TEXTURE = 7
    texture_name = material.texture
    width, height = material.texture_size
    # Since the location and format of the texture will only be known at
    # runtime, use zero for the offset and format. It will be filled in by the
    # engine during asset loading.
    return [gc.teximage_param(width, height, texture_name=texture_name),
        gc.texpllt_base(0, 0)]

CLEAR_TEXTURE_PARAMETERS = gc.teximage_param(0, 0, 0, 0)

def generate_face_attributes(material, flags):
    texture_attributes = (generate_texture_attributes(material)
        if material.texture else CLEAR_TEXTURE_PARAMETERS)
    polygon_attributes = gc.polygon_attr(light0=1, light1=1, light2=1, light3=1,
        alpha=int(flags.get("alpha", 31)), polygon_id=int(flags.get("id", 0)))
    scale = lambda components: gc.scale_components(components, 255)
    material_properties = (gc.dif_amb(scale(material.diffuse),
        scale(material.ambient), use256=True),
        gc.spe_emi(scale(material.specular), scale(material.emit), use256=True))
    return list(flatten([texture_attributes,  polygon_attributes,
        material_properties]))

def generate_normal(normal):
    return gc.normal(*normal)

def generate_vertex(location, scale_factor, vtx10=False):
    vtx = gc.vtx_10 if vtx10 else gc.vtx_16
    return vtx(location.x * scale_factor, location.y * scale_factor, location.z * scale_factor)

def determine_scale_factor(box):
    largest_coordinate = max(abs(box["wx"]), abs(box["wy"]), abs(box["wz"]))
    return 1.0 if largest_coordinate <= 7.9 else 7.9 / largest_coordinate

def generate_defaults():
    # todo: figure out light offsets, if we ever want to have
    # dynamic scene lights and stuff with vertex colors
    # default material, if no other material gets specified
    default_diffuse_color = 192, 192, 192
    default_ambient_color = 32, 32, 32
    return [gc.color(64, 64, 64, use256=True),
        gc.polygon_attr(light0=1, light1=1, light2=1, light3=1),
        gc.dif_amb(default_diffuse_color, default_ambient_color, use256=True)]

VTXS_TRIANGLE = 0
VTXS_QUAD = 1
def generate_polygon_list_start(points_per_polygon):
    assert points_per_polygon in (3, 4), "Invalid number of points in polygon: %d" % points_per_polygon
    return gc.begin_vtxs(VTXS_TRIANGLE if points_per_polygon == 3 else VTXS_QUAD)

def generate_face(material, mesh, face, scale_factor, vtx10=False):
    commands = []
    if not face.smooth_shading:
        commands.append(gc.normal(face.face_normal[0], face.face_normal[1], face.face_normal[2]))
    for vertex_index in range(len(face.vertices)):
        if material.texture:
            size = material.texture_size
            ds_u = face.uvlist[vertex_index][0] * size[0]
            ds_v = (1.0 - face.uvlist[vertex_index][1]) * size[1]
            commands.append(gc.texcoord(ds_u, ds_v))
        if face.smooth_shading:
            commands.append(generate_normal(face.vertex_normals[vertex_index]))
        vertex_location = mesh.vertices[face.vertices[vertex_index]].location
        commands.append(generate_vertex(vertex_location, scale_factor, vtx10))
    return list(flatten(commands))

def generate_faces(materials, mesh, scale_factor, vtx10=False):
    commands = []
    faces = sorted(mesh.polygons, key=lambda f:
        (f.vertexGroup(), f.material, len(f.vertices)))

    for group, group_faces in groupby(faces, methodcaller("vertexGroup")):
        commands.append(gc.push())
        if group == "__mixed":
            log.warning("This model uses mixed-group polygons! Animation for this is not yet implemented.")
        if group != "__mixed":
            commands.append(gc.mtx_mult_4x4(euclid.Matrix4(), tag=("bone", group)))
        for material_name, material_faces in groupby(group_faces, attrgetter("material")):
            commands.append(generate_face_attributes(materials[material_name], parse_material_flags(material_name)))
            for length, polytype_faces in groupby(material_faces, lambda f: len(f.vertices)):
                commands.append(generate_polygon_list_start(length))
                for face in polytype_faces:
                    commands.append(generate_face(materials[face.material], mesh, face, scale_factor, vtx10=False))
        commands.append(gc.pop())
    return list(flatten(commands))

def sort_polygons(polygon_list):
    return sorted(polygon_list, lambda p:
        (p.isMixed(), p.vertexGroup(), p.material, len(p.vertices)))

def generate_bounding_sphere(mesh):
    sphere = mesh.bounding_sphere()
    log.debug("Bounding sphere of radius %f centered at (%f, %f, %f)",
        sphere[1], sphere[0].x, sphere[0].y, sphere[0].z)
    return wrap_chunk("BSPH", struct.pack("< 32s i i i i",
        to_dsgx_string(mesh.name), to_fixed_point(sphere[0].x),
        to_fixed_point(sphere[0].z), to_fixed_point(sphere[0].y * -1),
        to_fixed_point(sphere[1])))

def generate_mesh(model, mesh, vtx10=False):
    commands = generate_command_list(model, mesh, vtx10)
    call_list, references = generate_gl_call_list(commands)
    dsgx_chunk = generate_dsgx(mesh.name, call_list)
    bsph_chunk = generate_bounding_sphere(mesh)
    cost_chunk = generate_cost(mesh, commands)
    return [dsgx_chunk, bsph_chunk, cost_chunk], references

def generate_references(commands, command_id):
    references = defaultdict(list)
    offset = 0
    for command in commands:
        offset += 1  # Go past the command word; the references point to the command data instead
        if command["instruction"] == command_id and command.get("tag"):
            references[command["tag"]].append(offset)
        offset += len(command["params"])
    return references

def generate_cost(mesh, commands):
    costs = {
        0x40: 1,
        0x20: 1,
        0x30: 4,
        0x18: 35,
        0x1B: 22,
        0x21: 12,
        0x29: 1,
        0x12: 36,
        0x11: 17,
        0x31: 4,
        0x22: 1,
        0x2A: 1,
        0x2B: 1,
        0x24: 8,
        0x23: 9,
    }
    cycles = sum(costs[command['instruction']] for command in commands)
    return wrap_chunk("COST", struct.pack("< 32s I I", to_dsgx_string(mesh.name), mesh.max_cull_polys(), cycles))

def generate_dsgx(mesh_name, call_list):
    return wrap_chunk("DSGX", to_dsgx_string(mesh_name) + call_list)

def generate_command_list(model, mesh, vtx10=False):
    gx_commands = []
    gx_commands.append(generate_defaults())
    scale_factor = determine_scale_factor(mesh.bounding_box())
    gx_commands.append(gc.push())
    gx_commands.append(gc.mtx_mult_4x4(model.global_matrix))
    if scale_factor != 1.0:
        inverse_scale = 1 / scale_factor
        gx_commands.append(gc.mtx_scale(inverse_scale, inverse_scale, inverse_scale))

    log.debug("Global Matrix: ")
    log.debug(model.global_matrix)

    gx_commands.append(generate_faces(model.materials, mesh, scale_factor, vtx10))

    gx_commands.append(gc.pop())
    return list(flatten(gx_commands))

def generate_gl_call_list(commands):
    call_list = []
    for command in commands:
        command_bytes = struct.pack("< B B B B", command["instruction"], 0, 0, 0)
        command_bytes += b"".join(command["params"])
        call_list.append(command_bytes)
    call_list = b"".join(call_list)
    return struct.pack("< I %ds" % len(call_list), int(len(call_list) / 4), call_list), dict(bones=generate_references(commands, 0x18), textures=generate_references(commands, 0x2A))

def generate_bones(animations, mesh_name, bone_references):
    if not animations:
        return
    name = to_dsgx_string(mesh_name)
    animation = animations[next(iter(animations.keys()))]
    bone_count = len(animation.channels.keys())
    bones = []
    for bone_name in sorted(animation.channels.keys()):
        if bone_name == "default":
            continue
        bone_offsets = bone_references.get(("bone", bone_name), [])
        bone_name = to_dsgx_string(bone_name)
        bones.append(struct.pack("< 32s I %dI" % len(bone_offsets), bone_name, len(bone_offsets), *bone_offsets))
    bones = b"".join(bones)
    return wrap_chunk("BONE", struct.pack("< 32s I %ds" % len(bones), name, bone_count, bones))

def generate_textures(mesh, texture_references):
    name = to_dsgx_string(mesh.name)
    count = len(texture_references)
    references = b"".join(struct.pack("< 32s I %dI" %
        len(texture_references[texture]), to_dsgx_string(texture),
        len(texture_references[texture]), *texture_references[texture])
        for texture in sorted(texture_references))
    return wrap_chunk("TXTR", struct.pack("< 32s I %ds" % len(references), name, count, references))

def generate_animations(animations):
    return [generate_animation(animations[animation], animation) for animation in animations]

def generate_animation(animation, animation_name):
    name = to_dsgx_string(animation_name)
    length = animation.length
    matrices = []
    for frame in range(animation.length):
        for bone_name in sorted(animation.channels.keys()):
            if bone_name == "default":
                continue
            matrix = animation.get_channel_data(bone_name, frame)
            matrices.append(struct.pack("< 16i", to_fixed_point(matrix.a), to_fixed_point(matrix.b), to_fixed_point(matrix.c), to_fixed_point(matrix.d), to_fixed_point(matrix.e), to_fixed_point(matrix.f), to_fixed_point(matrix.g), to_fixed_point(matrix.h), to_fixed_point(matrix.i), to_fixed_point(matrix.j), to_fixed_point(matrix.k), to_fixed_point(matrix.l), to_fixed_point(matrix.m), to_fixed_point(matrix.n), to_fixed_point(matrix.o), to_fixed_point(matrix.p)))
    matrices = b"".join(matrices)
    return wrap_chunk("BANI", struct.pack("< 32s I %ds" % len(matrices), name, length, matrices))

def generate(model, vtx10=False):
    chunks = []
    for mesh_name in model.meshes:
        mesh = model.meshes[mesh_name]
        mesh_chunks, references = generate_mesh(model, mesh, vtx10)
        chunks.append(mesh_chunks)
        if "bone" in model.animations:
            chunks.append(generate_bones(model.animations["bone"], mesh.name, references["bones"]))
        chunks.append(generate_textures(mesh, references["textures"]))
    if "bone" in model.animations:
        chunks.append(generate_animations(model.animations["bone"]))
    return list(flatten(chunk for chunk in chunks if chunk))

class Writer:
    def write(self, filename, model, vtx10=False):
        chunks = generate(model, vtx10)
        with open(filename, "wb") as fp:
            fp.write(b"".join(chunks))
