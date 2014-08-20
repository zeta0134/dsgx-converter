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

def main(args):
    if not valid_command_line_arguments(args):
        print("Usage: %s [file to convert]" % args[0])
        sys.exit(1)

    input_filename = args[1]
    output_filename = substitute_extension(input_filename, ".dsgx")

    if not known_file_type(input_filename):
        print("Unrecognized file type: " + file_extension(input_filename))
        sys.exit(1)

    model_to_convert = load_model_from_file(input_filename)

    display_model_info(model_to_convert)

    save_model_to_file(model_to_convert, output_filename)

def valid_command_line_arguments(args):
    return len(args) == 2

def substitute_extension(filename, extension):
    return os.path.splitext(filename)[0] + extension

def known_file_type(filename):
    return file_extension(filename) in _readers

def file_extension(filename):
    return os.path.splitext(filename)[1]

def load_model_from_file(filename):
    return _readers[file_extension(filename)](filename)

def display_model_info(model):
    print("Polygons: %d" % len(model.polygons))
    print("Vertecies: %d" % len(model.vertecies))

    # Count the number of texture maps in the model.
    tex = 0
    for poly in model.polygons:
        if poly.uvlist != None:
            tex += 1

    print("Textured Polygons: %d" % tex)

    print("Bounding Sphere: %s" % str(model.bounding_sphere()))
    print("Bounding Box: %s" % str(model.bounding_box()))

    print("Calculating culling cost...")
    print("Worst-case Draw Cost (in polys): %d" % model.max_cull_polys())

def save_model_to_file(model, filename):
    print("Attempting output...")
    dsgx.Writer().write(filename, model)
    print("Output Successful!")

def read_autodesk_fbx(filename):
    print("--Parsing FBX file--")
    #todo: not do all of this right here
    model = fbx_importer.Reader().read(filename)
    print("Not fully implemented! PANIC!")
    return model

def read_wavefront_obj(filename):
    print("---Parsing OBJ file---")
    return obj_importer.Reader().read(filename)

_readers = {
    ".fbx": read_autodesk_fbx,
    ".obj": read_wavefront_obj
}

if __name__ == '__main__':
    main(sys.argv)