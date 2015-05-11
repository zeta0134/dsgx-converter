import euclid3 as euclid

import logging
log = logging.getLogger()

class Model:
    def __init__(self):
        self.polygons = []
        self.materials = {}
        self.vertecies = []
        self.animations = {}
        self.groups = ["default"]

        self.global_matrix = euclid.Matrix4()
        
    class Vertex:
        def __init__(self, location=euclid.Vector3(0.0, 0.0, 0.0), model=None):
            # if a list or a tuple is passed in, convert it to a Vector3
            if type(location).__name__=='list' or type(location).__name__=='tuple':
                location = euclid.Vector3(location[0], location[1], location[2])
            
            self.location = location
            self.model = model
            self.group = "default"

        def setGroup(self, group):
            if group not in self.model.groups:
                self.model.groups.append(group)
            self.group = group
            
    class Polygon:
        def __init__(self, vertex_list = None, uvlist = None, material=None,
                     face_normal=None, vertex_normals=None, model=None):
            if vertex_list is None:
                self.vertecies = []
            else:
                self.vertecies = vertex_list
            self.material = material
            self.uvlist = uvlist
            self.face_normal = face_normal
            self.vertex_normals = vertex_normals
            self.model = model

        def vertexGroup(self):
            return self.model.vertecies[self.vertecies[0]].group

        def isMixed(self):
            orig = self.model.vertecies[self.vertecies[0]].group
            for v in self.vertecies:
                if orig != self.model.vertecies[v].group:
                    return True
            return False

    
    class Material:
        def __init__(self):
            self.texture = None
            self.ambient = (0, 0, 0)
            self.diffuse = (128, 128, 128)
            self.specular = (255, 255, 255)
            self.smooth_shading = False

    class Animation:
        def __init__(self):
            self.nodes = {}
            self.length = 0 #in frames
        
        def addNode(self, node_name, transform_list):
            #node_name = "Armature|"+node_name
            log.debug("Added animation node: %s", node_name)
            self.nodes[node_name] = transform_list

        def getTransform(self, node_name, frame):
            return self.nodes[node_name][frame]

    def createAnimation(self, name):
        self.animations[name] = self.Animation()

        return self.animations[name]

    def getAnimation(self, name):
        return self.animations[name]
    
    def addMaterial(self, name, ambient, specular, diffuse, texture=None, texwidth=0, texheight=0):
        newmtl = self.Material()
        newmtl.ambient = (ambient["r"], ambient["g"], ambient["b"])
        newmtl.specular = (specular["r"], specular["g"], specular["b"])
        newmtl.diffuse = (diffuse["r"], diffuse["g"], diffuse["b"])
        newmtl.texture = texture
        newmtl.texture_size = (texwidth, texheight)
        self.materials[name] = newmtl

    def addVertex(self, location=euclid.Vector3(0.0, 0.0, 0.0)):
        self.vertecies.append(self.Vertex(location, self))

    def addPoly(self, vertex_list=None, uvlist=None, vertex_normals=None, material=None):
        face_normal = self.face_normal(vertex_list)

        #if this is a 2-point polygon, turn it into a triangle; this will draw
        #on hardware as a perfect line segment
        if abs(self.vertecies[vertex_list[0]].location - self.vertecies[vertex_list[1]].location) < 0.01:
            log.debug("Encountered LINE SEGMENT variant 1")
            vertex_list = [vertex_list[0], vertex_list[2], vertex_list[2]]
            vertex_normals = [vertex_normals[0], vertex_normals[2], vertex_normals[2]]
            face_normal = euclid.Vector3(vertex_normals[0][0],vertex_normals[0][1],vertex_normals[0][2]) #pick one at random
        elif abs(self.vertecies[vertex_list[1]].location - self.vertecies[vertex_list[2]].location) < 0.01:
            log.debug("Encountered LINE SEGMENT variant 2")
            vertex_list = [vertex_list[0], vertex_list[1], vertex_list[1]]
            vertex_normals = [vertex_normals[0], vertex_normals[1], vertex_normals[1]]
            face_normal = euclid.Vector3(vertex_normals[0][0],vertex_normals[0][1],vertex_normals[0][2])
        elif abs(self.vertecies[vertex_list[2]].location - self.vertecies[vertex_list[0]].location) < 0.01:
            log.debug("Encountered LINE SEGMENT variant 3")
            vertex_list = [vertex_list[0], vertex_list[1], vertex_list[1]]
            vertex_normals = [vertex_normals[0], vertex_normals[1], vertex_normals[1]]
            face_normal = euclid.Vector3(vertex_normals[0][0],vertex_normals[0][1],vertex_normals[0][2])

        
        self.polygons.append(self.Polygon(vertex_list, uvlist, material,
                             face_normal, vertex_normals, self))
            

    def max_cull_polys(self):
        # for this model, compute the maximum number of polygons
        # that will ever be drawn at a given orientation.
        
        max = 0
        for testface in self.polygons:
            countPositive = 0
            countNegative = 0
            for face in self.polygons:
                angle = face.face_normal.dot(testface.face_normal)
                #print(angle)
                if angle >= 0:
                    countPositive += 1
                if angle < 0:
                    countNegative += 1
            if countPositive > max:
                max = countPositive
            if countNegative > max:
                max = countNegative

        return max

    def bounding_box(self):
        # returns a bounding box, as a dict of 6 values.
        # x,y,z indicate the negative side of the box, and
        # wx, wy, and wz are the width of the box.
        
        x,y,z = 0,0,0
        wx, wy, wz = 0,0,0
        for point in self.vertecies:
            x = min((x, point.location.x))
            y = min((y, point.location.y))
            z = min((z, point.location.z))
            wx = max((wx, point.location.x))
            wy = max((wy, point.location.y))
            wz = max((wz, point.location.z))
        
        # distance
        wx = wx - x
        wy = wy - y
        wz = wz - z
        
        return {
            'x': x,
            'y': y,
            'z': z,
            'wx': wx,
            'wy': wy,
            'wz': wz,
        }
        
    def bounding_sphere(self):
        # returns the center of the object, and the magnitude of the furthest
        # point from that center.

        midpoint = sum([point.location
                        for point in self.vertecies], 
                       euclid.Vector3()) / len(self.vertecies)
        
        radius = max( abs( abs(point.location - midpoint) )  for point in self.vertecies)
        return midpoint, radius


    def point_normal(self, vertex_index):
        # gather the face normals for every face which references this point                
        face_normals = [self.face_normal(face.vertecies)
                        for face in self.polygons
                            if vertex_index in face.vertecies]
        
        
        
        # if we didn't get any faces, there is *no normal*, since this is
        # just a point.
        if len(face_normals) == 0:
            return None
        
        # sum a list of tuples (blargh)
        result = [0.0, 0.0, 0.0]
        for normal in face_normals:
            result[0] += normal[0]
            result[1] += normal[1]
            result[2] += normal[2]
        
        # average
        result = (
            result[0] / len(face_normals),
            result[1] / len(face_normals),
            result[2] / len(face_normals),
        )
        
        return result

    def face_normal(self, vertex_list):
            # todo: implement different method for handling concave edges
            # using the first 3 points in this polygon, calculate the cross
            # product between the resulting edges
            
            v = []
            for index in vertex_list[:3]:
                v.append(self.vertecies[index].location)
            
            a = v[1] - v[0]
            b = v[1] - v[2]
            
            # take the cross product
            #normal = euclid.Vector3(a.y*b.z - a.z*b.y, a.z*b.x - a.x*b.z, a.x*b.y - a.y*b.x)
            normal = a.cross(b)
            
            # normalize
            normal.normalize()
            
            # print normal
            return normal
            
