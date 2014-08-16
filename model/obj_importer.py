from __future__ import with_statement
# import model
from model import euclid
from model import model

class Reader:
    def __init__(self):
        self.v = []
        self.vn = []
        self.vt = []
        self.f = []
        
        self.smoothingGroup = 0
        self.materials = {}
        self.current_material = None
        

    def read(self, filename):
        with open(filename) as fp:
            for line in fp.readlines():
                self.process_command(self.remove_comments(line))
        # ok, now we have the obj read in, convert it to a model
        object = model.Model()
        
        #add the materials to the model
        for k in self.materials.keys():
            object.addMaterial(k, self.materials[k]["ambient"], self.materials[k]["specular"], self.materials[k]["diffuse"])
        
        # First, add the vertecies
        for point in self.v:
            object.addVertex(euclid.Vector3(point['x'], point['y'], point['z']))
        
        # for each polygon in the model, add the appropriate
        # data to the model
        for face in self.f:
            # build a list of vertecies for this face
            points = []
            uvlist = []
            normals = []
            for point in face["points"]:
                # todo: make sure this data is valid!
                points.append(point['v'])
                # do we have a uvlist?
                uvlist = []
                if (point['vt'] != None):
                    uvlist.append( (
                            self.vt[point['vt']]['x'],
                            self.vt[point['vt']]['y'],
                    ) )
                if len(uvlist) == 0:
                    uvlist = None
                #similarly, do we have a Normals list?
                if (point['vn'] != None):
                    normals.append( (
                            self.vn[point['vn']]['x'],
                            self.vn[point['vn']]['y'],
                            self.vn[point['vn']]['z'],
                    ) )
            if len(normals) == 0:
                normals = None
            #object.polygons.append(model.Model.Polygon(points, uvlist))
            object.addPoly(points, uvlist, normals, face["material"]) # todo: vertex normals here
        
        return object
    
    def process_command(self, line):
        parts = line.split()
        if len(parts) > 0:
            if parts[0] in self.commands:
                self.commands[parts[0]](self, parts)
            else:
                print("Unrecognized command: {0}".format(parts[0]))
        
    def remove_comments(self, line):
        return line[:line.find("#")]
        
    def _vertex(self, parts):
        if len(parts) < 4:
            print("Bad 'v' command: not enough arguments")
        else:
            self.v.append({'x': float(parts[1]), 'y': float(parts[2]), 'z': float(parts[3])})
    
    def _vertex_normal(self, parts):
        if len(parts) < 4:
            print("Bad 'vn' command: not enough arguments")
        else:
            self.vn.append({'x': float(parts[1]), 'y': float(parts[2]), 'z': float(parts[3])})
    
    def _vertex_uv(self, parts):
        if len(parts) < 3:
            print("Bad 'vt' command: not enough arguments")
        else:
            self.vt.append({'x': float(parts[1]), 'y': float(parts[2])})

    def _face(self, parts):
        if len(parts) < 4:
            print("Bad 'f' command: not enough arguments to make a polygon (need 3 points)")
        else:
            # A polygon is a list of points, normals, and uv coords. The last two
            # can be omitted, in which case they should be ignored.
            poly = []
            for part in parts[1:]:
                pieces = part.split("/")
                point = int(float(pieces[0])) - 1 # note: -1 converts index to 0 based
                texture = None
                if len(pieces) > 1 and pieces[1] is not "":
                    texture = int(float(pieces[1])) - 1
                normal = None
                if len(pieces) > 2 and pieces[2] is not "":
                    normal = int(float(pieces[2])) - 1
                poly.append({'v': point, 'vt': texture, 'vn': normal})
                
            # todo maybe: check for invalid polys?
            # todo perhaps: check for and convert negative reference numbers?
            # todo perhaps: check for and use smoothing group for polys
            self.f.append({"points": poly, "material": self.current_material})
    
    def _smoothing_group(self, parts):
        # sets the current smoothing group. This will be utilized by
        # polygons which do not have vertex normals. (maybe)
        if len(parts) > 1:
            self.smoothingGroup = int(float(parts[1]))
        else:
            print("Bad 's' command: needs an argument.")
            
    def _mtllib(self, parts):
        print("Loading material library: " + parts[1])
        
        with open(parts[1]) as fp:
            for line in fp.readlines():
                self.process_command(self.remove_comments(line))
    
    def _usemtl(self, parts):
        if parts[1] in self.materials:
            self.current_material = parts[1]
        else:
            print("Bad material reference: " + parts[1])
        
    def _new_material(self, parts):
        self.materials[parts[1]] = {}
        self.current_material = parts[1]
    
    def _mtl_Ns(self, parts):
        #shininess exponent, or something; different modeling programs interpret this value differently.
        self.materials[self.current_material]["Ns"] = parts[1]
    
    def _mtl_ambient_color(self, parts):
        self.materials[self.current_material]["ambient"] = {"r": float(parts[1]), "g": float(parts[2]), "b": float(parts[3])}
    
    def _mtl_diffuse_color(self, parts):
        self.materials[self.current_material]["diffuse"] = {"r": float(parts[1]), "g": float(parts[2]), "b": float(parts[3])}
    
    def _mtl_specular_color(self, parts):
        self.materials[self.current_material]["specular"] = {"r": float(parts[1]), "g": float(parts[2]), "b": float(parts[3])}
        

    commands = {
        # .obj commands
        "v": _vertex,
        "vn": _vertex_normal,
        "vt": _vertex_uv,
        "f": _face,
        #"s": _smoothing_group,
        "mtllib": _mtllib,
        "usemtl": _usemtl,
        # .mtl commands
        "newmtl": _new_material,
        "Ns": _mtl_Ns,
        "Ka": _mtl_ambient_color,
        "Kd": _mtl_diffuse_color,
        "Ks": _mtl_specular_color,
    }