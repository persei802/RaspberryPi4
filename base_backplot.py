#!/usr/bin/env python
import gcode
import shutil
import os

from qtvcp.core import Info, Status
from base_canon import BaseCanon

INFO = Info()
STATUS = Status()

class BaseBackPlot(object):
    def __init__(self, inifile=None, canon=BaseCanon):
        inifile = inifile or os.getenv("INI_FILE_NAME")
        if inifile is None or not os.path.isfile(inifile):
            raise ValueError("Invalid INI file: %s", inifile)
        self.canon_class = canon
        self.canon = None
        self.config_dir = os.path.dirname(inifile)
        temp = INFO.get_error_safe_setting("EMCIO", "RANDOM_TOOLCHANGER")
        self.random = int(temp or 0)
        temp = INFO.get_error_safe_setting("TRAJ", "COORDINATES", 'XYZ')
        self.geometry = temp.upper()
        temp = INFO.get_error_safe_setting("DISPLAY", "LATHE", "false")
        self.lathe_option = temp.lower() in ["1", "true", "yes"]
        temp = INFO.get_error_safe_setting("RS274NGC", "PARAMETER_FILE", "linuxcnc.var")
        self.parameter_file = os.path.join(self.config_dir, temp)
        self.temp_parameter_file = os.path.join(self.parameter_file + '.temp')
        self.last_filename = None

    def load(self, filename=None, *args, **kwargs):
        # args and kwargs are passed to the canon init method
        filename = filename or self.last_filename
        if filename is None:
            filename = STATUS.stat.file
        if filename is None or not os.path.isfile(filename):
            self.canon = None
            print("Can't load backplot, invalid file: {}".format(filename))
        self.last_filename = filename

        # create the object which handles the canonical motion callbacks
        # (straight_feed, straight_traverse, arc_feed, rigid_tap, etc.)
        self.canon = self.canon_class(*args, **kwargs)
        if os.path.exists(self.parameter_file):
            shutil.copy(self.parameter_file, self.temp_parameter_file)
        self.canon.parameter_file = self.temp_parameter_file

        # Some initialization g-code to set the units and optional user code
        unitcode = "G21"
        initcode = INFO.get_error_safe_setting("RS274NGC", "RS274NGC_STARTUP_CODE", "")

        # THIS IS WHERE IT ALL HAPPENS: load_preview will execute the code,
        # call back to the canon with motion commands, and record a history
        # of all the movements.

        result, seq = gcode.parse(filename, self.canon, unitcode, initcode)
        if result > gcode.MIN_ERROR:
            msg = gcode.strerror(result)
            fname = os.path.basename(filename)
            print("3D plot - Error in {} line {}".format(fname, seq - 1), msg)

        # clean up temp var file and the backup
        os.unlink(self.temp_parameter_file)
        os.unlink(self.temp_parameter_file + '.bak')


if __name__ == "__main__":
    from base_canon import PrintCanon
    INI_FILE = "/home/pi/linuxcnc/configs/vtk_dragon/qtdragon_xyz.ini"
    NGC_FILE = "/home/pi/linuxcnc/nc_files/test200x200.ngc"
    gr = BaseBackPlot(INI_FILE, canon=PrintCanon)
    gr.load(NGC_FILE)

