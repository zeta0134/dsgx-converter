import struct # , model
# Writer: given a Model type, this converts it to an
# nds object, and outputs several files-- a base model
# for direct DMA into the NDS GX engine, and a listing
# of animations and their offsets to adjust the base for
# deformation.
class Writer:        
    def write(self, filename, model):
        gx = Emitter()
        
        # basically, for each face given, output the appropriate
        # type of polygon. We loop twice, once for triangles, once
        # for quads. (ignore every other type)
        
        # todo: figure out light offsets, if we ever want to have
        # dynamic scene lights and stuff with vertex colors
        gx.color(128, 128, 128, True) #use256 mode
        gx.polygon_attr(light0=1, light1=1)
        
        self.current_material = ""
        
        for polytype in range(3,5):
            if (polytype == 3):
                gx.begin_vtxs(gx.vtxs_triangle)
            if (polytype == 4):
                gx.begin_vtxs(gx.vtxs_quad)
            for face in model.polygons:            
                if len(face.vertecies) == polytype:
                    if face.material != self.current_material:
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
                        self.current_material = face.material
                        print("Switching to mtl: " + face.material)
                    shading = "smooth"
                    if shading == "flat":
                        # handle color
                        gx.normal(
                            face.face_normal[0],
                            face.face_normal[1],
                            face.face_normal[2],
                        )
                    for point in face.vertecies:
                        # point normal
                        if shading == "smooth":
                            p_normal = model.point_normal(point)
                            if p_normal == None:
                                print("Problem: no normal for this point!", face.vertecies)
                            else:
                                #handle color
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
        
        fp = open(filename, "wb")
        #first, output the bounding sphere. (todo: make a real header!!)
        out = bytes()
        sphere = model.bounding_sphere()
        print(sphere[0].x)
        out += struct.pack("<ffff", sphere[0].x / 4.0, sphere[0].y / 4.0, sphere[0].z / 4.0, sphere[1] / 4.0)
        #then, the cull-cost for the object
        out += struct.pack("<I", model.max_cull_polys())
        print(len(out))
        fp.write(out)
        fp.write(gx.write(filename))
        fp.close()


# Emitter: caches and writes commands for the GX
# engine, with proper command packing when applicible.
# note: *does not* know which commands require which
# parameters-- make sure you're passing in the correct
# amounts or the real DS hardware will be freaking out
class Emitter:
    def __init__(self):
        self.commands = []
    
    def command(self, command, parameters = []):
        cmd = {'instruction': command, 'params': parameters}
        self.commands.append(cmd)

    def write(self, packed=False):
        # todo: modify this heavily, allow packed commands
        out = bytes()
        for cmd in self.commands:
            # pad the command with 0's for unpacked mode
            
            out += struct.pack("<BBBB", cmd['instruction'], 0,0,0)
            for param in cmd['params']:
                out += struct.pack("<I", param)
                
        # ok. Last thing, we need the size of the finished
        # command list, for glCallList to use.
        out = struct.pack("<I", int(len(out)/4)) + out
        #done ^_^
        return out
    
    # these are the individual commands, as defined in GBATEK, organized
    # in ascending order by command byte. For a full command reference, see
    # GBATEK, at http://nocash.emubase.de/gbatek.htm
    
    vtxs_triangle = 0
    vtxs_quad = 1
    vtxs_triangle_strip = 2
    vtxs_quadstrip = 3    
    def begin_vtxs(self, format):
        self.command(0x40, [format & 0x3])
        
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
        x = x/4
        y = y/4
        z = z/4
        
        self.command(0x23, [
            (int(x * 2**12) & 0xFFFF) + 
            ((int(y * 2**12) & 0xFFFF) << 16),
            (int(z * 2**12) & 0xFFFF)
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
            attr
        ])
        
    def color(self, red, green, blue, use256=False):
        if (use256):
            # DS colors are in 16bit mode (5 bits per value)
            red = int(red/8)
            blue = int(blue/8)
            green = int(green/8)
        self.command(0x20, [
            (red & 0x1F) + 
            ((green & 0x1F) << 5) + 
            ((blue & 0x1F) << 10)
        ])
    
    def normal(self, x, y, z):
        self.command(0x21, [
            (int((x*0.95) * 2**9) & 0x3FF) + 
            ((int((y*0.95) * 2**9) & 0x3FF) << 10) + 
            ((int((z*0.95) * 2**9) & 0x3FF) << 20) 
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
            (diffuse[0] & 0x1F) + 
            ((diffuse[1] & 0x1F) << 5) + 
            ((diffuse[2] & 0x1F) << 10) + 
            ((setvertex & 0x1) << 15) +
            ((ambient[0] & 0x1F) << 16) + 
            ((ambient[1] & 0x1F) << 21) + 
            ((ambient[2] & 0x1F) << 26) 
        ])