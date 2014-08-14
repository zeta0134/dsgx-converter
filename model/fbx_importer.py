# import model
from model import euclid
from model import model

from FbxCommon import *

class Reader:
    def __init__(self):
        pass

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
                        print("A mesh!")
                        print("Polygons: ", mesh.GetPolygonCount())
                        print("Control points: ", len(mesh.GetControlPoints()))

                        #this list contains all the points in the model; polygons will
                        #index into this list
                        vertex_list = mesh.GetControlPoints()

                        #add the verticies to the model
                        for i in range(len(vertex_list)):
                            object.addVertex(euclid.Vector3(vertex_list[i][0], vertex_list[i][1], vertex_list[i][2]))

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
                                            print("normals!")
                                            #if normals.GetMappingMode() == FbxLayerElement.eByControlPoint:
                                            print("mapping!")
                                            normal = normal_data.GetDirectArray().GetAt(v)
                                            print(normal)
                                            normals.append((normal[0],normal[1],normal[2]))

                                #todo: not discard UV coordinates here
                                uvlist = None
                                object.addPoly(points, uvlist, normals)

            return object

