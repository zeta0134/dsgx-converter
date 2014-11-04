import euclid3 as euclid
from .model import Model
import os
from PIL import Image

from FbxCommon import InitializeSdkObjects, LoadScene, FbxNodeAttribute, FbxSurfacePhong, FbxAnimStack, FbxTime, FbxAMatrix, FbxTexture, FbxLayerElement

def fbx_to_euclid(input_matrix):
    return euclid.Matrix4.new(
        input_matrix.Get(0,0),input_matrix.Get(1,0),input_matrix.Get(2,0),input_matrix.Get(3,0),
        input_matrix.Get(0,1),input_matrix.Get(1,1),input_matrix.Get(2,1),input_matrix.Get(3,1),
        input_matrix.Get(0,2),input_matrix.Get(1,2),input_matrix.Get(2,2),input_matrix.Get(3,2),
        input_matrix.Get(0,3),input_matrix.Get(1,3),input_matrix.Get(2,3),input_matrix.Get(3,3))



class Reader:
    def __init__(self):
        self.material_index = []
        self.bones = {}
        self.cluster_transforms = {}
        pass

    def process_clusters(self, object, mesh):
        # each mesh should contain a single deformer, containing
        # multiple clusters; roughly each cluster corresponds
        # to each bone in our models.
        if mesh.GetDeformerCount() > 0:
            deformer = mesh.GetDeformer(0)
            # loop over all the bones

            for i in range(deformer.GetClusterCount()):
                cluster = deformer.GetCluster(i)

                transform_link_matrix = FbxAMatrix()
                transform_matrix = FbxAMatrix()
                cluster.GetTransformLinkMatrix(transform_link_matrix) #if this even works
                cluster.GetTransformMatrix(transform_matrix) #if this even works
                self.cluster_transforms[cluster.GetLink().GetName()] = fbx_to_euclid(transform_matrix) * fbx_to_euclid(transform_link_matrix).inverse()
                #print("Cluster: ", cluster.GetLink().GetName())
                #print(self.cluster_transforms[cluster.GetLink().GetName()])
                #print(fbx_to_euclid(transform_matrix))

                #print(cluster.GetLink().GetName(), ": ", cluster.GetControlPointIndicesCount())
                # loop over every point this bone controlls
                for j in range(cluster.GetControlPointIndicesCount()):
                    if object.vertecies[cluster.GetControlPointIndices()[j]].group != "default":
                        print("Oh no! Multiple bones affect the same vertex. Bad things!!")
                    object.vertecies[cluster.GetControlPointIndices()[j]].setGroup(cluster.GetLink().GetName())

    def process_materials(self, object, fbx_mesh):
        material_count = fbx_mesh.GetNode().GetMaterialCount()
        #print("Layer count: ", fbx_mesh.GetLayerCount())
        for l in range(fbx_mesh.GetLayerCount()):
            for i in range(material_count):
                material = fbx_mesh.GetNode().GetMaterial(i)
                #print("Material: ", material.GetName())
                if material.GetClassId().Is(FbxSurfacePhong.ClassId):
                    #check for and process textures
                    texture_name = None
                    texture_width = 1
                    texture_height = 1
                    if material.Diffuse.GetSrcObjectCount(FbxTexture.ClassId) > 0:
                        texture = material.Diffuse.GetSrcObject(FbxTexture.ClassId,0)
                        texture_name = os.path.basename(texture.GetFileName())
                        texture_name = os.path.splitext(texture_name)[0]
                        print("Found texture: ", texture_name)
                        try:
                            image = Image.open(texture.GetFileName())
                            texture_width = image.size[0]
                            texture_height = image.size[1]
                        except:
                            print("Could not load texture file: ", texture.GetFileName())



                    #print("Is phong!")
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
                         "b": material.Diffuse.Get()[2]},
                         texture_name, texture_width, texture_height)


    #TODO: More gracefully handle multiple meshes in a single file; we would need to
    #offset the vertex count somehow when coding in polygons.
    def process_mesh(self, object, mesh):
        # Import polygon and vertex data.
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

        print("Mesh Global Transform:")
        print(fbx_to_euclid(mesh.GetNode().EvaluateGlobalTransform()))
        #exit()
        #well ... that explains a lot.
        self.mesh_global = fbx_to_euclid(mesh.GetNode().EvaluateGlobalTransform())
        object.global_matrix = self.mesh_global

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
                        uv_data = mesh.GetLayer(l).GetUVs()
                        if uv_data:
                            if uv_data.GetMappingMode() == FbxLayerElement.eByControlPoint:
                                print("eByControlPoint not supported for UVs!")
                            elif uv_data.GetMappingMode() ==  FbxLayerElement.eByPolygonVertex:
                                uv_index = mesh.GetTextureUVIndex(face, v)
                                uv = uv_data.GetDirectArray().GetAt(uv_index)
                                #print("UVs: ", uv)
                                uvlist.append((uv[0], uv[1]))

                #todo: not discard UV coordinates here
                if len(uvlist) == 0:
                    uvlist = None
                object.addPoly(points, uvlist, normals, mesh.GetNode().GetMaterial(material_map.GetAt(face)).GetName())

        self.process_clusters(object, mesh)

    def process_skeleton(self, object, skeleton):
        #TODO: This obviously.
        #print("SKELETON encountered!")
        self.bones[skeleton.GetName()] = skeleton
        return

    def process_node(self, object, node):
        if node.GetNodeAttribute() == None:
            print("NULL Node Attribute: ", node.GetName())
        else:
            attribute = node.GetNodeAttribute()
            attribute_type = attribute.GetAttributeType()

            if attribute_type == FbxNodeAttribute.eMesh:
                self.process_mesh(object, attribute)
            if attribute_type == FbxNodeAttribute.eSkeleton:
                self.process_skeleton(object, attribute)

        #regardless of emptiness, if this node has any children, we process those as well
        for i in range(node.GetChildCount()):
            #print("recursing into: ", node.GetName())
            self.process_node(object, node.GetChild(i))

    def calculate_transformation(self, bone, frame, last_step=True):
        timestamp = FbxTime()
        timestamp.SetFrame(frame)
        #animation_transform = bone.GetNode().EvaluateLocalTransform(timestamp)
        animation_transform = bone.GetNode().EvaluateGlobalTransform(timestamp)

        #make this euclid format please
        animation_transform = fbx_to_euclid(animation_transform)

        bind_pose_inverse = self.cluster_transforms[bone.GetNode().GetName()]

        #print("\n".join(sorted(dir(bone.GetNode().GetScene().GetRootNode()))))
        #exit()

        #animation_transform = self.cluster_transforms[bone.GetNode().GetName()].inverse() * animation_transform
        #animation_transform = animation_transform.identity()
        #return euclid.Matrix4()
        
        #print(bone.GetNode().GetName())
        return bind_pose_inverse * animation_transform
        
        #return self.mesh_global * animation_transform * bind_pose.inverse() * self.mesh_global.inverse()

        #return animation_transform.inverse()

    def process_animation(self, object, scene):
        #print(sorted(dir(scene)))
        #evaluator = scene.GetAnimationEvaluator()
        #print(sorted(dir(evaluator)))

        for i in range(scene.GetSrcObjectCount(FbxAnimStack.ClassId)):
            animation_stack = scene.GetSrcObject(FbxAnimStack.ClassId, i)
            #print("Animation: ", animation_stack.GetName())
            #print("Length: ", animation_stack.LocalStop.Get().GetFrameCount())

            #evaluator.SetContext(animation_stack)
            scene.SetCurrentAnimationStack(animation_stack)
            obj_animation = object.createAnimation(animation_stack.GetName())
            obj_animation.length = animation_stack.LocalStop.Get().GetFrameCount()

            #initialize our list of animation stuffs
            for k in self.bones:
                transform_list = []
                for frame in range(obj_animation.length):
                    transform_list.append(self.calculate_transformation(self.bones[k], frame))

                obj_animation.addNode(self.bones[k].GetName(), transform_list)


    def read(self, filename):
        #first, make sure we can open the file
        SdkManager, scene = InitializeSdkObjects()
        if not LoadScene(SdkManager, scene, filename):
            print("Could not parse " + filename + " as .fbx, bailing.")
            return
        else:
            object = Model()

            #Process all nodes in the scene
            node_list = scene.GetRootNode()
            for i in range(node_list.GetChildCount()):
                self.process_node(object, node_list.GetChild(i))

            #animation is handled separately for some weird reason
            self.process_animation(object, scene)

            return object

