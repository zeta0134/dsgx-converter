import euclid3 as euclid
from .model import Model

import logging
log = logging.getLogger("assimp_importer")
log.setLevel(logging.DEBUG)

import pyassimp

class Reader:
    def __init__(self):
      pass

    def read(self, filename):
      log.debug("Importing %s with assimp...", filename)
      scene = pyassimp.load(filename)

      log.debug("Meshes: %d", len(scene.meshes))
      log.debug("Mateirals: %d", len(scene.materials))
      log.debug("Textures: %d", len(scene.textures))

      log.critical("ASSIMP NOT FINISHED!!")
      return None