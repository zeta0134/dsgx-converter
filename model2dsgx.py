#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Created on Thu Oct 21 00:31:54 2010

@author: Nicholas Flynt, Cristián Romo
"""
from model import obj_importer
from model import fbx_importer
from model import dsgx

from fbx import *

import sys
import os

if len(sys.argv) < 2:
    print("Usage: model2dsgx.py [file to convert]")
    sys.exit(1)

inputname = sys.argv[1]

# Get the extension and decide which importer to use from it.
file_root, file_extension = os.path.splitext(inputname)

def read_autodesk_fbx(filename):
    print("--Parsing FBX file--")
    #todo: not do all of this right here
    model = fbx_importer.Reader().read(inputname)
    print("Not fully implemented! PANIC!")
    return model

def read_wavefront_obj(filename):
    print("---Parsing OBJ file---")
    return obj_importer.Reader().read(inputname)

readers = {
    ".fbx": read_autodesk_fbx,
    ".obj": read_wavefront_obj
}
if file_extension not in readers:
    print("Unrecognized extension: " + file_extension)
    sys.exit(1)
model_to_convert = readers[file_extension](inputname)

outfilename = file_root + '.dsgx'

# Display information about the model.
print("Polygons: %d" % len(model_to_convert.polygons))
print("Vertecies: %d" % len(model_to_convert.vertecies))

# Count the number of texture maps in the model.
tex = 0
for poly in model_to_convert.polygons:
    if poly.uvlist != None:
        tex += 1

print("Textured Polygons: %d" % tex)

print("Bounding Sphere: %s" % str(model_to_convert.bounding_sphere()))
print("Bounding Box: %s" % str(model_to_convert.bounding_box()))

print("Calculating culling cost...")
print("Worst-case Draw Cost (in polys): %d" % model_to_convert.max_cull_polys())

# Write the .dsgx file from the in memory model.
print("Attempting output...")
dsgx.Writer().write(outfilename, model_to_convert)
print("Output Successful!")
