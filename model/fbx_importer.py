# import model
from model import euclid
from model import model

from FbxCommon import InitializeSdkObjects, LoadScene, FbxNodeAttribute, FbxSurfacePhong

class Reader:
    def __init__(self):
        material_index = []
        pass



    def process_materials(self, object, fbx_mesh):
        material_count = fbx_mesh.GetNode().GetMaterialCount()
        print("Layer count: ", fbx_mesh.GetLayerCount())
        for l in range(fbx_mesh.GetLayerCount()):
            for i in range(material_count):
                material = fbx_mesh.GetNode().GetMaterial(i)
                print("Material: ", material.GetName())
                if material.GetClassId().Is(FbxSurfacePhong.ClassId):
                    print("Is phong!")
                    #this is a valid enough material to add, so do it!
                    object.addMaterial(material.GetName(), 
                        {"r": material.Ambient.Get()[0], 
                         "g": material.Ambient.Get()[1], 
                         "b": material.Ambient.Get()[2]},

                        {"r": material.Specular.Get()[0], 
                         "g": material.Specular.Get()[1], 
                         "b": material.Specular.Get()[2]},

                        {"r": material.Diffuse.Get()[0], 
                         "g": material.Diffuse.Get()[1], 
                         "b": material.Diffuse.Get()[2]})

    def read(self, filename):
        #first, make sure we can open the file
        SdkManager, scene = InitializeSdkObjects()
        if not LoadScene(SdkManager, scene, filename):
            print("Could not parse " + filename + " as .fbx, bailing.")
            return
        else:
            object = model.Model()

            #do some stuff!
            node_list = scene.GetRootNode()
            for i in range(node_list.GetChildCount()):
                node = node_list.GetChild(i)
                if node.GetNodeAttribute() == None:
                    print("NULL Node Attribute")
                else:
                    attribute_type = node.GetNodeAttribute().GetAttributeType()

                    if attribute_type == FbxNodeAttribute.eMesh:
                        #this is a mesh; import the polygon and vertex data
                        mesh = node.GetNodeAttribute()
                        print("Polygons: ", mesh.GetPolygonCount())
                        print("Verticies: ", len(mesh.GetControlPoints()))

                        #this list contains all the points in the model; polygons will
                        #index into this list
                        vertex_list = mesh.GetControlPoints()

                        #add the verticies to the model
                        for i in range(len(vertex_list)):
                            object.addVertex(euclid.Vector3(vertex_list[i][0], vertex_list[i][1], vertex_list[i][2]))

                        #do something about materials
                        self.process_materials(object, mesh)
                        material_map = mesh.GetLayer(0).GetMaterials().GetIndexArray()

                        for face in range(mesh.GetPolygonCount()):
                            #this importer only supports triangles and
                            #quads, so we need to throw out any weird
                            #sizes here
                            vertex_count = mesh.GetPolygonSize(face)
                            if vertex_count >= 3 and vertex_count <= 4:
                                points = []
                                normals = []
                                uvlist = []
                                for v in range(vertex_count):
                                    points.append(mesh.GetPolygonVertex(face,v))

                                    #figure out if there's normal data?
                                    #TODO: Why does this need to loop over layer data? Investigate!
                                    for l in range(mesh.GetLayerCount()):
                                        normal_data = mesh.GetLayer(l).GetNormals()
                                        if normal_data:
                                            normal = normal_data.GetDirectArray().GetAt(v)
                                            #print(normal)
                                            normals.append((normal[0],normal[1],normal[2]))

                                #todo: not discard UV coordinates here
                                uvlist = None
                                object.addPoly(points, uvlist, normals, mesh.GetNode().GetMaterial(material_map.GetAt(face)).GetName())

            return object

