# Gaslight PIL into thinking that PySide2 is PySide6.
# PySide6 is not available on Raspbian Bullseye, but the API is close enough that this works.
from PySide2 import QtCore, QtGui
import sys
sys.modules["PySide6.QtCore"] = QtCore
sys.modules["PySide6.QtGui"] = QtGui
from PIL import Image, ImageOps, ImageQt
