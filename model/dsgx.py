import euclid3 as euclid
import struct # , model
# Writer: given a Model type, this converts it to an
# nds object, and outputs several files-- a base model
# for direct DMA into the NDS GX engine, and a listing
# of animations and their offsets to adjust the base for
# deformation.

def toFixed(float_value, fraction=12):
        return int(float_value * pow(2,fraction))

class Writer:        
    def write_chunk(self, fp, name, data):
        if len(name) != 4:
            print("Cannot write chunk: ", name, ", wrong size for header!")
            return

        #write the name as a non-null terminated 4-byte sequence
        fp.write(struct.pack("<cccc", name[0].encode('ascii'), name[1].encode('ascii'), name[2].encode('ascii'), name[3].encode('ascii')))

        #write out the length of data, in WORDS. (4-bytes per word)
        length = len(data)
        if length % 4 != 0:
            padding = 4 - (length % 4)
            length = length + padding
            for i in range(padding):
                data = data + struct.pack("<x")
        fp.write(struct.pack("<I", int(length / 4)))

        #finally, write out the data itself
        fp.write(data)
        print("Wrote chunk: ", name)
        print("Length: ", int(length / 4))

    def dsgx_string(self, str):
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

    def face_attributes(self, gx, face, model):
        #write out per-polygon lighting and texture data, but only when that
        #data is different from the previous polygon
        if face.material != self.current_material:
            self.current_material = face.material
            print("Switching to mtl: " + face.material)
            if model.materials[self.current_material].texture != None:
                print("Material has texture! Writing texture info out now.")
                texture_name = model.materials[self.current_material].texture
                if not texture_name in self.texture_offsets:
                    self.texture_offsets[texture_name] = []
                self.texture_offsets[texture_name].append(gx.offset + 1)

                size = model.materials[self.current_material].texture_size
                gx.teximage_param(256 * 1024, size[0], size[1], 7)

                
            else:
                print("Material has no texture; outputting dummy teximage to clear state")
                gx.teximage_param(0, 0, 0, 0)

            gx.dif_amb(
                (
                    model.materials[face.material].diffuse[0] * 255,
                    model.materials[face.material].diffuse[1] * 255,
                    model.materials[face.material].diffuse[2] * 255), #diffuse
                (
                    model.materials[face.material].ambient[0] *  model.materials[face.material].diffuse[0] * 255,
                    model.materials[face.material].ambient[1] *  model.materials[face.material].diffuse[1] * 255,
                    model.materials[face.material].ambient[2] *  model.materials[face.material].diffuse[2] * 255), #ambient fanciness
                False, #setVertexColor (not sure)
                True # use256
            )

            shading = "smooth"
            if shading == "flat":
                # handle color
                gx.normal(
                    face.face_normal[0],
                    face.face_normal[1],
                    face.face_normal[2],
                )

    def output_vertex(self, gx, point, model):
        # point normal
        p_normal = model.point_normal(point)
        if p_normal == None:
            print("Problem: no normal for this point!", face.vertecies)
        else:
            gx.normal(
                p_normal[0],
                p_normal[1],
                p_normal[2],
            )
        # location
        gx.vtx_16(
            model.vertecies[point].location.x,
            model.vertecies[point].location.y,
            model.vertecies[point].location.z
        )


    def write(self, filename, model):
        gx = Emitter()
        
        # basically, for each face given, output the appropriate
        # type of polygon. We loop twice, once for triangles, once
        # for quads. (ignore every other type)
        
        # todo: figure out light offsets, if we ever want to have
        # dynamic scene lights and stuff with vertex colors
        gx.color(64, 64, 64, True) #use256 mode
        gx.polygon_attr(light0=1, light1=1)

        # default material, if no other material gets specified
        gx.dif_amb(
            (192,192,192), # diffuse
            (32,32,32),    # ambient fanciness
            False,         # setVertexColor (not sure)
            True           # use256
        )
        
        self.current_material = None
        self.group_offsets = {}
        self.texture_offsets = {}

        #process faces that all belong to one vertex group (simple case)
        for group in model.groups:
            #print("Group: ", group)
            gx.push()

            #store this transformation offset for later
            if not group in self.group_offsets:
                self.group_offsets[group] = []
            self.group_offsets[group].append(gx.offset + 1) #skip over the command itself; we need a reference to the parameters

            #gx.mtx_mult_4x4(model.animations["Armature|Idle1"].getTransform(group, 15))
            gx.mtx_mult_4x4(model.global_matrix)

            for polytype in range(3,5):
                if (polytype == 3):
                    gx.begin_vtxs(gx.vtxs_triangle)
                if (polytype == 4):
                    gx.begin_vtxs(gx.vtxs_quad)

                for face in model.polygons:
                    if face.vertexGroup() == group and not face.isMixed():
                        if len(face.vertecies) == polytype:
                            self.face_attributes(gx, face, model)
                            for p in range(len(face.vertecies)):
                                # uv coordinate
                                if model.materials[self.current_material].texture:
                                    #print(p)
                                    #two things here:
                                    #1. The DS has limited precision, and expects texture coordinates based on the size of the texture, so
                                    #   we multiply the UV coordinates such that 0.0, 1.0 maps to 0.0, <texture size>
                                    #2. UV coordinates are typically specified relative to the bottom-left of the image, but the DS again
                                    #   expects coordinates from the top-left, so we need to invert the V coordinate to compensate.
                                    size = model.materials[self.current_material].texture_size
                                    gx.texcoord(face.uvlist[p][0] * size[0], (1.0 - face.uvlist[p][1]) * size[1])
                                    #print("Emitted UV coord: ", face.uvlist[p][0] * size[0], (1.0 - face.uvlist[p][1]) * size[1])
                                self.output_vertex(gx, face.vertecies[p], model)

            gx.pop()

        #now process mixed faces; similar, but we need to switch matricies *per point* rather than per face
        for polytype in range(3,5):
            if (polytype == 3):
                gx.begin_vtxs(gx.vtxs_triangle)
            if (polytype == 4):
                gx.begin_vtxs(gx.vtxs_quad)

            for face in model.polygons:
                if len(face.vertecies) == polytype:
                    if face.isMixed():
                        self.face_attributes(gx, face, model)
                        for point in face.vertecies:
                            gx.push()

                            #store this transformation offset for later
                            group = model.vertecies[point].group
                            if not group in self.group_offsets:
                                self.group_offsets[group] = []
                            self.group_offsets[group].append(gx.offset + 1) #skip over the command itself; we need a reference to the parameters

                            #gx.mtx_mult_4x4(model.animations["Armature|Idle1"].getTransform(model.vertecies[point].group, 15))
                            gx.mtx_mult_4x4(euclid.Matrix4())
                            self.output_vertex(gx, point, model)
                            gx.pop()

        
        fp = open(filename, "wb")
        #first things first, output the main data
        self.write_chunk(fp, "DSGX", gx.write())

        #then, output the bounding sphere data (needed for multipass stuffs)
        bsph = bytes()
        sphere = model.bounding_sphere()
        bsph += struct.pack("<iiii", toFixed(sphere[0].x), toFixed(sphere[0].z), toFixed(sphere[0].y * -1), toFixed(sphere[1]))
        print("Bounding Sphere:")
        print("X: ", sphere[0].x)
        print("Y: ", sphere[0].y)
        print("Z: ", sphere[0].z)
        print("Radius: ", sphere[1])
        
        self.write_chunk(fp, "BSPH", bsph)

        #output the cull-cost for the object
        self.write_chunk(fp, "COST", struct.pack("<I", model.max_cull_polys()))

        #matrix offsets for each bone
        bone = bytes()
        bone += struct.pack("<I", len(self.group_offsets)) #number of bones in the file
        for group in sorted(self.group_offsets):
            bone += self.dsgx_string(group) #name of this bone
            bone += struct.pack("<I", len(self.group_offsets[group])) #number of copies of this matrix in the dsgx file

            #debug
            print("Writing bone data for:  ", group)
            print("Number of offsets: ", len(self.group_offsets[group]))

            for offset in self.group_offsets[group]:
                bone += struct.pack("<I", offset)
                #print(offset, " ", end="")
            #print("")
        self.write_chunk(fp, "BONE", bone)

        #texparam offsets for each texture
        txtr = bytes()
        txtr += struct.pack("<I", len(self.texture_offsets))
        print("Total number of textures: ", len(self.texture_offsets))
        for texture in sorted(self.texture_offsets):
            txtr += self.dsgx_string(texture) #name of this texture

            txtr += struct.pack("<I", len(self.texture_offsets[texture])) #number of references to this texture in the dsgx file

            #debug!
            print("Writing texture data for: ", texture)
            print("Number of references: ", len(self.texture_offsets[texture]))

            for offset in self.texture_offsets[texture]:
                txtr += struct.pack("<I", offset)
        self.write_chunk(fp, "TXTR", txtr)

        #animation data!
        for animation in model.animations:
            bani = bytes()
            bani += self.dsgx_string(animation)
            bani += struct.pack("<I", model.animations[animation].length)
            print("Writing animation data: ", animation)
            print("Length in frames: ", model.animations[animation].length)
            #here, we output bone data per frame of the animation, making
            #sure to use the same bone order as the BONE chunk
            for frame in range(model.animations[animation].length):
                for group in sorted(self.group_offsets):
                    matrix = model.animations[animation].getTransform(group, frame)
                    #hoo boy
                    bani += struct.pack("<iiii", toFixed(matrix.a), toFixed(matrix.b), toFixed(matrix.c), toFixed(matrix.d))
                    bani += struct.pack("<iiii", toFixed(matrix.e), toFixed(matrix.f), toFixed(matrix.g), toFixed(matrix.h))
                    bani += struct.pack("<iiii", toFixed(matrix.i), toFixed(matrix.j), toFixed(matrix.k), toFixed(matrix.l))
                    bani += struct.pack("<iiii", toFixed(matrix.m), toFixed(matrix.n), toFixed(matrix.o), toFixed(matrix.p))
            self.write_chunk(fp, "BANI", bani)
        
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
        
    def end_vtxs(self):
        pass #dummy command, real hardware does nothing, no point in outputting
    
    def vtx_16(self, x, y, z):
        # given vertex coordinates as floats, convert them into
        # 16bit fixed point numerals with 12bit fractional parts,
        # and pack them into two commands.
        
        # note: this command is ignoring overflow completely, do note that
        # values outside of the range (approx. -8 to 8) will produce strange
        # results.
        
        # cheat
        #x = x/4
        #y = y/4
        #z = z/4
        
        self.command(0x23, [
            struct.pack("<I",
            (int(x * 2**12) & 0xFFFF) |
            ((int(y * 2**12) & 0xFFFF) << 16)),
            struct.pack("<I",(int(z * 2**12) & 0xFFFF))
        ])
    
    polygon_mode_modulation = 0
    polygon_mode_normal = 0
    polygon_mode_decal = 1
    polygon_mode_toon = 2
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
    
    def normal(self, x, y, z):
        self.command(0x21, [
            struct.pack("<I",
            (int((x*0.95) * 2**9) & 0x3FF) + 
            ((int((y*0.95) * 2**9) & 0x3FF) << 10) + 
            ((int((z*0.95) * 2**9) & 0x3FF) << 20))
        ])
        
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

    def push(self):
        self.command(0x11)

    def pop(self):
        self.command(0x12, [struct.pack("<I",0x1)])

    #note: expects a euclid.py matrix, any other format will not work
    def mtx_mult_4x4(self, matrix):
        self.command(0x18, [
                struct.pack("<i",toFixed(matrix.a)), struct.pack("<i",toFixed(matrix.b)), struct.pack("<i",toFixed(matrix.c)), struct.pack("<i",toFixed(matrix.d)), 
                struct.pack("<i",toFixed(matrix.e)), struct.pack("<i",toFixed(matrix.f)), struct.pack("<i",toFixed(matrix.g)), struct.pack("<i",toFixed(matrix.h)), 
                struct.pack("<i",toFixed(matrix.i)), struct.pack("<i",toFixed(matrix.j)), struct.pack("<i",toFixed(matrix.k)), struct.pack("<i",toFixed(matrix.l)), 
                struct.pack("<i",toFixed(matrix.m)), struct.pack("<i",toFixed(matrix.n)), struct.pack("<i",toFixed(matrix.o)), struct.pack("<i",toFixed(matrix.p))
            ])

    def texcoord(self, u, v):
        self.command(0x22, [
            struct.pack("<I",
            (int(u * 2**4) & 0xFFFF) |
            ((int(v * 2**4) & 0xFFFF) << 16))])

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
