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
    --debug         Display debugging info
    --quiet         Silence all but Warnings and Errors
    --vtx10         Output 10-bit vertex coordinates (default is 16-bit)

"""
from docopt import docopt
import logging
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger()

import os, sys
from model import dsgx, fbx_importer, obj_importer, assimp_importer


def main(args):
    arguments = docopt(__doc__, version="0.1a")
    adjust_logging_level(arguments)

    input_filename = arguments["<input_filename>"]
    output_filename = determine_output_filename(input_filename, arguments)

    model_to_convert = load_model(input_filename)
    display_model_info(model_to_convert)
    save_model_as_dsgx(model_to_convert, output_filename, arguments)

def adjust_logging_level(arguments):
    if arguments["--debug"]:
        log.setLevel(logging.DEBUG)
    elif arguments["--quiet"]:
        log.setLevel(logging.WARN)
    else:
        log.setLevel(logging.INFO)

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
    if known_file_type(filename):
        return _readers[file_extension(filename)](filename)
    else:
        return read_using_assimp(filename)

def display_model_info(model):
    log.info("Polygons: %d" % len(model.polygons))
    log.info("Vertecies: %d" % len(model.vertecies))

    textured_polygons = sum(1 for polygon in model.polygons if polygon.uvlist)
    log.info("Textured Polygons: %d" % textured_polygons)

    log.info("Bounding Sphere: %s" % str(model.bounding_sphere()))
    log.info("Bounding Box: %s" % str(model.bounding_box()))

    log.info("Worst-case Draw Cost (polygons): %d" % model.max_cull_polys())

def save_model_as_dsgx(model, filename, arguments):
    log.debug("Attempting output...")
    dsgx.Writer().write(filename, model, arguments["--vtx10"])
    log.debug("Output Successful!")

def read_autodesk_fbx(filename):
    log.debug("--Parsing FBX file--")
    model = fbx_importer.Reader().read(filename)
    return model

def read_wavefront_obj(filename):
    log.debug("---Parsing OBJ file---")
    return obj_importer.Reader().read(filename)

def read_using_assimp(filename):
    log.debug("---Falling back to ASSIMP---")
    return assimp_importer.Reader().read(filename)

_readers = {
    ".fbx": read_autodesk_fbx,
    ".obj": read_wavefront_obj,
}

if __name__ == '__main__':
    main(sys.argv)
