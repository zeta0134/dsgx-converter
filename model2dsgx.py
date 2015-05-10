#!/usr/local/bin/python
# -*- coding: utf-8 -*-
"""
DSGX Converter for Nintendo DS Homebrew
Created on Thu Oct 21 00:31:54 2010

@author: Nicholas Flynt, Cristián Romo

Usage:
    model2dsgx.py [options] <input_filename>
    model2dsgx.py [options] <input_filename> <output_filename>

Options:
    -h --help       Print this message and exit
    -v --version    Show version number and exit
    --vtx10         Output 10-bit vertex coordinates (default is 16-bit)

"""
import os, sys
from model import dsgx, fbx_importer, obj_importer
from docopt import docopt

def main(args):
    arguments = docopt(__doc__, version="0.1a")
    print(arguments)

    input_filename = arguments["<input_filename>"]
    output_filename = determine_output_filename(input_filename, arguments)

    if not known_file_type(input_filename):
        error_exit(1,
            "Unrecognized file type: " + file_extension(input_filename))

    model_to_convert = load_model(input_filename)
    display_model_info(model_to_convert)
    save_model_as_dsgx(model_to_convert, output_filename, arguments)

def determine_output_filename(input_filename, args):
    if "<output_filename>" in args:
        return args["<output_filename>"]
    return substitute_extension(input_filename, ".dsgx")

def error_exit(status_code, error_message=""):
    if error_message:
        print(error_message)
    sys.exit(status_code)

def substitute_extension(filename, extension):
    return os.path.splitext(filename)[0] + extension

def known_file_type(filename):
    return file_extension(filename) in _readers

def file_extension(filename):
    return os.path.splitext(filename)[1]

def load_model(filename):
    return _readers[file_extension(filename)](filename)

def display_model_info(model):
    print("Polygons: %d" % len(model.polygons))
    print("Vertecies: %d" % len(model.vertecies))

    textured_polygons = sum(1 for polygon in model.polygons if polygon.uvlist)
    print("Textured Polygons: %d" % textured_polygons)

    print("Bounding Sphere: %s" % str(model.bounding_sphere()))
    print("Bounding Box: %s" % str(model.bounding_box()))

    print("Worst-case Draw Cost (polygons): %d" % model.max_cull_polys())

def save_model_as_dsgx(model, filename, arguments):
    print("Attempting output...")
    dsgx.Writer().write(filename, model, arguments["--vtx10"])
    print("Output Successful!")

def read_autodesk_fbx(filename):
    print("--Parsing FBX file--")
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