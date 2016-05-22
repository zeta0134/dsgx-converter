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
import types

import euclid3 as euclid
import model.geometry_command as gc
from model.geometry_command import _to_fixed_point

log = logging.getLogger()
WORD_SIZE_BYTES = 4

def reconcile(new):
    """Ensure two functions return the same values given the same arugments."""
    def reconcile_decorator(old):
        def reconciler(*args, **kwargs):
            expected_result = old(*args, **kwargs)
            new_result = new(*args, **kwargs)
            assert expected_result == new_result, \
                ("unable to reconcile function results: %s returned %s but %s returned %s" %
                (old.__name__, repr(expected_result), new.__name__,
                repr(new_result)))
            return expected_result
        return reconciler
    return reconcile_decorator

def compact(iterable):
    return (element for element in iterable if element)

# from https://stackoverflow.com/a/10824420
def flatten(container):
    for i in container:
        if isinstance(i, (list, tuple, types.GeneratorType)):
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
    return {parts[0]: parts[1] if parts[1:] else True for parts in flag_parts}

def generate_texture_attributes(material):
    width, height = material.texture_size
    # Since the location and format of the texture will only be known at
    # runtime, use zero for the offset and format. It will be filled in by the
    # engine during asset loading.
    return [gc.teximage_param(width, height, texture_name=material.texture),
        gc.texpllt_base(0, 0)]

CLEAR_TEXTURE_PARAMETERS = gc.teximage_param(0, 0)

def generate_face_attributes(material, flags):
    texture_attributes = (generate_texture_attributes(material)
        if material.texture else CLEAR_TEXTURE_PARAMETERS)
    polygon_attributes = gc.polygon_attr(light0=1, light1=1, light2=1, light3=1,
        alpha=int(flags.get("alpha", 31)), polygon_id=int(flags.get("id", 0)))
    scale = lambda components: gc._scale_components(components, 255)
    material_properties = (gc.dif_amb(scale(material.diffuse),
        scale(material.ambient), use_24bit=True),
        gc.spe_emi(scale(material.specular), scale(material.emit),
        use_24bit=True))
    return list(flatten([texture_attributes,  polygon_attributes,
        material_properties]))

def generate_vertex(location, scale_factor, vtx10=False):
    vtx = gc.vtx_10 if vtx10 else gc.vtx_16
    return vtx(location.x * scale_factor, location.y * scale_factor, location.z * scale_factor)

def determine_scale_factor(box):
    largest_coordinate = max(abs(box["wx"]), abs(box["wy"]), abs(box["wz"]))
    return 1.0 if largest_coordinate <= 7.9 else 7.9 / largest_coordinate

def generate_defaults():
    default_diffuse_color = 192, 192, 192
    default_ambient_color = 32, 32, 32
    return [gc.color(64, 64, 64, use_24bit=True),
        gc.polygon_attr(light0=1, light1=1, light2=1, light3=1),
        gc.dif_amb(default_diffuse_color, default_ambient_color,
        use_24bit=True)]

def generate_polygon_list_start(points_per_polygon):
    assert points_per_polygon in (3, 4), \
        "invalid number of points in polygon: %d" % points_per_polygon
    return gc.begin_vtxs(gc.PrimitiveType.SEPARATE_TRIANGLES
        if points_per_polygon == 3 else
        gc.PrimitiveType.SEPAPATE_QUADRILATERALS)

def generate_face(material, vertices, face, scale_factor, vtx10=False):
    commands = [gc.normal(*face.face_normal)
        if not face.smooth_shading else None]
    for i, vertex in enumerate(face.vertices):
        if material.texture:
            commands.append(gc.texcoord(
                face.uvlist[i][0] * material.texture_size[0],
                (1.0 - face.uvlist[i][1]) * material.texture_size[1]))
        if face.smooth_shading:
            commands.append(gc.normal(*face.vertex_normals[i]))
        commands.append(generate_vertex(vertices[vertex].location,
            scale_factor, vtx10))
    return list(compact(flatten(commands)))

def generate_faces(materials, mesh, scale_factor, vtx10=False):
    vertex_count = lambda face: len(face.vertices)
    face_material = attrgetter("material")
    face_group = methodcaller("vertexGroup")
    faces = sorted(mesh.polygons, key=lambda f:
        (f.vertexGroup(), f.material, len(f.vertices)))

    commands = []
    for group, group_faces in groupby(faces, face_group):
        commands.append(gc.push())
        if group == "__mixed":
            log.warning("use of mixed-group polygons found: animation for this is not yet implemented")
        else:
            commands.append(gc.mtx_mult_4x4(euclid.Matrix4(),
                tag=("bone", group)))
        for material_name, material_faces in groupby(group_faces,
            face_material):
            commands.append(generate_face_attributes(materials[material_name],
                parse_material_flags(material_name)))
            for points_per_face, polytype_faces in groupby(material_faces,
                vertex_count):
                commands.append(generate_polygon_list_start(points_per_face))
                for face in polytype_faces:
                    commands.append(generate_face(materials[face.material],
                        mesh.vertices, face, scale_factor, vtx10))
        commands.append(gc.pop())
    return list(flatten(commands))

def generate_bounding_sphere(mesh_name, sphere):
    log.debug("Bounding sphere of radius %f centered at (%f, %f, %f)",
        sphere[1], sphere[0].x, sphere[0].y, sphere[0].z)
    return wrap_chunk("BSPH", struct.pack("< 32s i i i i",
        to_dsgx_string(mesh_name), _to_fixed_point(sphere[0].x),
        _to_fixed_point(sphere[0].z), _to_fixed_point(sphere[0].y * -1),
        _to_fixed_point(sphere[1])))

def generate_mesh(model, mesh, vtx10=False):
    commands = generate_command_list(model, mesh, vtx10)
    call_list, references = generate_gl_call_list(commands)
    dsgx_chunk = generate_dsgx(mesh.name, call_list)
    bsph_chunk = generate_bounding_sphere(mesh.name, mesh.bounding_sphere())
    cost_chunk = generate_cost(mesh, commands)
    return [dsgx_chunk, bsph_chunk, cost_chunk], references

def generate_references(commands, command_id):
    references = defaultdict(list)
    offset = 0
    for command in commands:
        # Go past the command word; the references point to the command data
        # instead, as the references only need to modify the data - never the
        # command.
        offset += 1
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
    for bone_name in sorted(set(animation.channels.keys()) - {"default"}):
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
        for bone_name in sorted(set(animation.channels.keys()) - {"default"}):
            matrix = animation.get_channel_data(bone_name, frame)
            matrices.append(struct.pack("< 16i", _to_fixed_point(matrix.a), _to_fixed_point(matrix.b), _to_fixed_point(matrix.c), _to_fixed_point(matrix.d), _to_fixed_point(matrix.e), _to_fixed_point(matrix.f), _to_fixed_point(matrix.g), _to_fixed_point(matrix.h), _to_fixed_point(matrix.i), _to_fixed_point(matrix.j), _to_fixed_point(matrix.k), _to_fixed_point(matrix.l), _to_fixed_point(matrix.m), _to_fixed_point(matrix.n), _to_fixed_point(matrix.o), _to_fixed_point(matrix.p)))
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
