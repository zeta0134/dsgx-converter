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

#process args here

#debug: remove for final build
if (len(sys.argv) < 2):
    print("Usage: model2dsgx.py [file to convert]")
    exit()
else:
    inputname = sys.argv[1]

#figure out the filename, do different stuff depending
file_name,file_extension = os.path.splitext(inputname)

if file_extension == ".fbx":
    print("--Parsing FBX file--")

    #todo: not do all of this right here
    piki = fbx_importer.Reader().read(inputname)

    print("Not fully implemented! PANIC!")
    #exit()
elif file_extension == ".obj":
    print("---Parsing OBJ file---")
    piki = obj_importer.Reader().read(inputname)
else:
    print("Unrecognized extension: " + file_extension)
    exit()

outfilename = inputname[:inputname.rfind('.')] + '.dsgx'

#output debug stuffs
print("Polygons: ", len(piki.polygons))
print("Vertecies: ", len(piki.vertecies))

#polys with uv maps?
tex = 0
for poly in piki.polygons:
    if (poly.uvlist != None):
        tex += 1

print("Textured Polygons: ", tex)

print("Bounding Sphere: ", piki.bounding_sphere())
print("Bounding Box: ", piki.bounding_box())

print("Calculating culling cost...")
print("Worst-case Draw Cost (in polys): ", piki.max_cull_polys())

#attempt to output the object as a dsgx file
print("Attempting output...")
dsgx.Writer().write(outfilename, piki)
print("Output Successful!")

#model.dsgx.Writer().write(model.load(input.filename), output.filename)
