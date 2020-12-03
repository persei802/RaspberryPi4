#!/usr/bin/env python
import os
import hal
import hal_glib
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtWebKitWidgets import QWebView, QWebPage
from qtvcp.widgets.gcode_editor import GcodeEditor as GCODE
from qtvcp.widgets.mdi_line import MDILine as MDI_WIDGET
from qtvcp.widgets.tool_offsetview import ToolOffsetView as TOOL_TABLE
from qtvcp.widgets.origin_offsetview import OriginOffsetView as OFFSET_VIEW
from qtvcp.widgets.stylesheeteditor import StyleSheetEditor as SSE
from qtvcp.widgets.file_manager import FileManager as FM
from qtvcp.lib.keybindings import Keylookup
from qtvcp.lib.gcodes import GCodes
from qtvcp.core import Status, Action, Info, Path
from qtvcp import logger
from shutil import copyfile
from vtk_backplot import VTKBackPlot

LOG = logger.getLogger(__name__)
KEYBIND = Keylookup()
STATUS = Status()
INFO = Info()
ACTION = Action()
PATH = Path()

# constants for tab pages
TAB_MAIN = 0
TAB_FILE = 1
TAB_OFFSETS = 2
TAB_TOOL = 3
TAB_STATUS = 4
TAB_PROBE = 5
TAB_CAMERA = 6
TAB_GCODES = 7
TAB_SETUP = 8
TAB_SETTINGS = 9
TAB_ACCESSORIES = 10

class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.h = halcomp
        self.w = widgets
        self.gcodes = GCodes(widgets)
        self.valid = QtGui.QDoubleValidator(-999.999, 999.999, 3)
        self.styleeditor = SSE(widgets, paths)
        KEYBIND.add_call('Key_F12','on_keycall_F12')
        KEYBIND.add_call('Key_Pause', 'on_keycall_pause')

        # some global variables
        self.probe = None
        self.default_setup = os.path.join(PATH.CONFIGPATH, "default_setup.html")
        self.start_line = 0
        self.run_time = 0
        self.time_tenths = 0
        self.timer_on = False
        self.home_all = False
        self.min_spindle_rpm = INFO.MIN_SPINDLE_SPEED
        self.max_spindle_rpm = INFO.MAX_SPINDLE_SPEED
        self.max_linear_velocity = INFO.MAX_TRAJ_VELOCITY
        self.system_list = ["G54","G55","G56","G57","G58","G59","G59.1","G59.2","G59.3"]
        self.slow_jog_factor = 10
        self.reload_tool = 0
        self.last_loaded_program = ""
        self.first_turnon = True
        self.lineedit_list = ["work_height", "touch_height", "sensor_height", "laser_x", "laser_y",
                              "sensor_x", "sensor_y", "camera_x", "camera_y",
                              "search_vel", "probe_vel", "max_probe", "eoffset_count"]
        self.onoff_list = ["frame_program", "frame_tool", "frame_touchoff", "frame_dro", "frame_override", "frame_status"]
        self.axis_a_list = ["label_axis_a", "dro_axis_a", "action_zero_a", "axistoolbutton_a",
                            "action_home_a", "widget_jog_angular", "widget_increments_angular",
                            "a_plus_jogbutton", "a_minus_jogbutton"]

        STATUS.connect('general', self.dialog_return)
        STATUS.connect('state-on', lambda w: self.enable_onoff(True))
        STATUS.connect('state-off', lambda w: self.enable_onoff(False))
        STATUS.connect('mode-manual', lambda w: self.enable_auto(False))
        STATUS.connect('mode-mdi', lambda w: self.enable_auto(False))
        STATUS.connect('mode-auto', lambda w: self.enable_auto(True))
        STATUS.connect('gcode-line-selected', lambda w, line: self.set_start_line(line))
        STATUS.connect('hard-limits-tripped', self.hard_limit_tripped)
        STATUS.connect('program-pause-changed', lambda w, state: self.w.btn_spindle_pause.setEnabled(state))
        STATUS.connect('actual-spindle-speed-changed', lambda w, speed: self.update_rpm(speed))
        STATUS.connect('user-system-changed', lambda w, data: self.user_system_changed(data))
        STATUS.connect('metric-mode-changed', lambda w, mode: self.metric_mode_changed(mode))
        STATUS.connect('file-loaded', self.file_loaded)
        STATUS.connect('homed', self.homed)
        STATUS.connect('all-homed', self.all_homed)
        STATUS.connect('not-all-homed', self.not_all_homed)
        STATUS.connect('periodic', lambda w: self.update_runtimer())
        STATUS.connect('command-stopped', lambda w: self.stop_timer())

    def class_patch__(self):
        self.old_fman = FM.load
        FM.load = self.load_code

    def initialized__(self):
        self.init_pins()
        self.init_preferences()
        self.init_widgets()
        self.init_vtk()
        self.init_probe()
        self.init_utils()
        self.w.stackedWidget_log.setCurrentIndex(0)
        self.w.stackedWidget.setCurrentIndex(0)
        self.w.stackedWidget_dro.setCurrentIndex(0)
        self.w.btn_spindle_pause.setEnabled(False)
        self.w.btn_touch_sensor.setEnabled(self.w.chk_use_tool_sensor.isChecked())
        self.w.page_buttonGroup.buttonClicked.connect(self.main_tab_changed)
        self.w.filemanager.onUserClicked()    
        self.w.filemanager_usb.onMediaClicked()
        self.chk_use_sensor_changed(self.w.chk_use_tool_sensor.isChecked())
        self.chk_use_touchplate_changed(self.w.chk_use_touchplate.isChecked())
        self.chk_run_from_line_checked(self.w.chk_run_from_line.isChecked())
        self.chk_use_camera_changed(self.w.chk_use_camera.isChecked())
        self.w.widget_custom_buttons.hide()
    # hide widgets for A axis if not present
        if "A" not in INFO.AVAILABLE_AXES:
            for i in self.axis_a_list:
                self.w[i].hide()
            self.w.lbl_increments_linear.setText("INCREMENTS")
    # set validators for lineEdit widgets
        for val in self.lineedit_list:
            self.w['lineEdit_' + val].setValidator(self.valid)
    # check for default setup html file
        try:
            self.web_page.mainFrame().load(QtCore.QUrl.fromLocalFile(self.default_setup))
        except Exception as e:
            print("No default setup file found - {}".format(e))

    # connect vtk backplot control buttons
        self.w.btn_view_p.clicked.connect(self.vtkbackplot.setViewP)
        self.w.btn_view_x.clicked.connect(self.vtkbackplot.setViewX)
        self.w.btn_view_y.clicked.connect(self.vtkbackplot.setViewY)
        self.w.btn_view_z.clicked.connect(self.vtkbackplot.setViewZ)
        self.w.btn_zoom_in.clicked.connect(self.vtkbackplot.zoomIn)
        self.w.btn_zoom_out.clicked.connect(self.vtkbackplot.zoomOut)
        self.w.btn_view_clear.clicked.connect(self.vtkbackplot.clearLivePlot)
#        self.w.btn_machine_bounds.clicked.connect(lambda state: self.vtkbackplot.showMachineBounds(state))
#        self.w.btn_program_bounds.clicked.connect(lambda state: self.vtkbackplot.showProgramBounds(state))
#        self.w.btn_machine_labels.clicked.connect(lambda state: self.vtkbackplot.showMachineLabels(state))
#        self.w.btn_program_labels.clicked.connect(lambda state: self.vtkbackplot.showProgramLabels(state))
        self.w.btn_machine_bounds.clicked.connect(self.showMachineBounds)
        self.w.btn_program_bounds.clicked.connect(self.showProgramBounds)
        self.w.btn_machine_labels.clicked.connect(self.showMachineLabels)
        self.w.btn_program_labels.clicked.connect(self.showProgramLabels)

    #############################
    # SPECIAL FUNCTIONS SECTION #
    #############################
    def init_pins(self):
        # spindle control pins
        pin = self.h.newpin("spindle_amps", hal.HAL_FLOAT, hal.HAL_IN)
        hal_glib.GPin(pin).connect("value_changed", self.spindle_pwr_changed)
        pin = self.h.newpin("spindle_volts", hal.HAL_FLOAT, hal.HAL_IN)
        hal_glib.GPin(pin).connect("value_changed", self.spindle_pwr_changed)
        pin = self.h.newpin("spindle_fault", hal.HAL_U32, hal.HAL_IN)
        hal_glib.GPin(pin).connect("value_changed", self.spindle_fault_changed)
        pin = self.h.newpin("modbus-errors", hal.HAL_U32, hal.HAL_IN)
        hal_glib.GPin(pin).connect("value_changed", self.mb_errors_changed)
        self.h.newpin("spindle_pause", hal.HAL_BIT, hal.HAL_OUT)
        # external offset control pins
        self.h.newpin("eoffset_enable", hal.HAL_BIT, hal.HAL_OUT)
        self.h.newpin("eoffset_clear", hal.HAL_BIT, hal.HAL_OUT)
        self.h.newpin("eoffset_count", hal.HAL_S32, hal.HAL_OUT)
        pin = self.h.newpin("eoffset_value", hal.HAL_FLOAT, hal.HAL_IN)

    def init_preferences(self):
        if not self.w.PREFS_:
            self.add_status("CRITICAL - no preference file found, enable preferences in screenoptions widget")
            return
        self.last_loaded_program = self.w.PREFS_.getpref('last_loaded_file', None, str,'BOOK_KEEPING')
        self.reload_tool = self.w.PREFS_.getpref('Tool to load', 0, int,'CUSTOM_FORM_ENTRIES')
        self.w.lineEdit_laser_x.setText(str(self.w.PREFS_.getpref('Laser X', 100, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_laser_y.setText(str(self.w.PREFS_.getpref('Laser Y', -20, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_sensor_x.setText(str(self.w.PREFS_.getpref('Sensor X', 10, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_sensor_y.setText(str(self.w.PREFS_.getpref('Sensor Y', 10, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_camera_x.setText(str(self.w.PREFS_.getpref('Camera X', 10, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_camera_y.setText(str(self.w.PREFS_.getpref('Camera Y', 10, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_work_height.setText(str(self.w.PREFS_.getpref('Work Height', 20, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_touch_height.setText(str(self.w.PREFS_.getpref('Touch Height', 40, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_sensor_height.setText(str(self.w.PREFS_.getpref('Sensor Height', 40, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_search_vel.setText(str(self.w.PREFS_.getpref('Search Velocity', 40, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_probe_vel.setText(str(self.w.PREFS_.getpref('Probe Velocity', 10, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_max_probe.setText(str(self.w.PREFS_.getpref('Max Probe', 10, float, 'CUSTOM_FORM_ENTRIES')))
        self.w.lineEdit_eoffset_count.setText(str(self.w.PREFS_.getpref('Eoffset count', 0, int, 'CUSTOM_FORM_ENTRIES')))
        self.w.chk_eoffsets.setChecked(self.w.PREFS_.getpref('External offsets', False, bool, 'CUSTOM_FORM_ENTRIES'))
        self.w.chk_reload_program.setChecked(self.w.PREFS_.getpref('Reload program', False, bool,'CUSTOM_FORM_ENTRIES'))
        self.w.chk_reload_tool.setChecked(self.w.PREFS_.getpref('Reload tool', False, bool,'CUSTOM_FORM_ENTRIES'))
        self.w.chk_use_keyboard.setChecked(self.w.PREFS_.getpref('Use keyboard', False, bool, 'CUSTOM_FORM_ENTRIES'))
        self.w.chk_run_from_line.setChecked(self.w.PREFS_.getpref('Run from line', False, bool, 'CUSTOM_FORM_ENTRIES'))
        self.w.chk_use_virtual.setChecked(self.w.PREFS_.getpref('Use virtual keyboard', False, bool, 'CUSTOM_FORM_ENTRIES'))
        self.w.chk_use_tool_sensor.setChecked(self.w.PREFS_.getpref('Use tool sensor', False, bool, 'CUSTOM_FORM_ENTRIES'))
        self.w.chk_use_touchplate.setChecked(self.w.PREFS_.getpref('Use tool touchplate', False, bool, 'CUSTOM_FORM_ENTRIES'))
        self.w.chk_use_camera.setChecked(self.w.PREFS_.getpref('Use camera', False, bool, 'CUSTOM_FORM_ENTRIES'))
        self.w.chk_alpha_mode.setChecked(self.w.PREFS_.getpref('Use alpha display mode', False, bool, 'CUSTOM_FORM_ENTRIES'))
        
    def closing_cleanup__(self):
        if not self.w.PREFS_: return
        self.w.PREFS_.putpref('last_loaded_directory', os.path.dirname(self.last_loaded_program), str, 'BOOK_KEEPING')
        self.w.PREFS_.putpref('last_loaded_file', self.last_loaded_program, str, 'BOOK_KEEPING')
        self.w.PREFS_.putpref('Tool to load', STATUS.get_current_tool(), int, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Laser X', self.w.lineEdit_laser_x.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Laser Y', self.w.lineEdit_laser_y.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Sensor X', self.w.lineEdit_sensor_x.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Sensor Y', self.w.lineEdit_sensor_y.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Camera X', self.w.lineEdit_camera_x.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Camera Y', self.w.lineEdit_camera_y.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Work Height', self.w.lineEdit_work_height.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Touch Height', self.w.lineEdit_touch_height.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Sensor Height', self.w.lineEdit_sensor_height.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Search Velocity', self.w.lineEdit_search_vel.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Probe Velocity', self.w.lineEdit_probe_vel.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Max Probe', self.w.lineEdit_max_probe.text().encode('utf-8'), float, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Eoffset count', self.w.lineEdit_eoffset_count.text().encode('utf-8'), int, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('External offsets', self.w.chk_eoffsets.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Reload program', self.w.chk_reload_program.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Reload tool', self.w.chk_reload_tool.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Use keyboard', self.w.chk_use_keyboard.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Run from line', self.w.chk_run_from_line.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Use virtual keyboard', self.w.chk_use_virtual.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Use tool sensor', self.w.chk_use_tool_sensor.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Use tool touchplate', self.w.chk_use_touchplate.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Use camera', self.w.chk_use_camera.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        self.w.PREFS_.putpref('Use alpha display mode', self.w.chk_alpha_mode.isChecked(), bool, 'CUSTOM_FORM_ENTRIES')
        if self.probe:
            self.probe.closing_cleanup__()

    def init_widgets(self):
        self.w.main_tab_widget.setCurrentIndex(TAB_MAIN)
        self.w.slider_jog_linear.setMaximum(INFO.MAX_LINEAR_JOG_VEL)
        self.w.slider_jog_linear.setValue(INFO.DEFAULT_LINEAR_JOG_VEL)
        self.w.slider_jog_angular.setMaximum(INFO.MAX_ANGULAR_JOG_VEL)
        self.w.slider_jog_angular.setValue(INFO.DEFAULT_ANGULAR_JOG_VEL)
        self.w.slider_maxv_ovr.setMaximum(self.max_linear_velocity)
        self.w.slider_maxv_ovr.setValue(self.max_linear_velocity)
        self.w.slider_feed_ovr.setMaximum(INFO.MAX_FEED_OVERRIDE)
        self.w.slider_feed_ovr.setValue(100)
        self.w.slider_rapid_ovr.setMaximum(100)
        self.w.slider_rapid_ovr.setValue(100)
        self.w.slider_spindle_ovr.setMinimum(INFO.MIN_SPINDLE_OVERRIDE)
        self.w.slider_spindle_ovr.setMaximum(INFO.MAX_SPINDLE_OVERRIDE)
        self.w.slider_spindle_ovr.setValue(100)
        self.w.chk_override_limits.setChecked(False)
        self.w.chk_override_limits.setEnabled(False)
        self.w.lbl_maxv_percent.setText("100 %")
        self.w.lbl_max_rapid.setText(str(self.max_linear_velocity))
        self.w.lbl_home_x.setText(INFO.get_error_safe_setting('JOINT_0', 'HOME',"50"))
        self.w.lbl_home_y.setText(INFO.get_error_safe_setting('JOINT_1', 'HOME',"50"))
        self.w.cmb_gcode_history.addItem("No File Loaded")
        self.w.cmb_gcode_history.wheelEvent = lambda event: None
        self.w.jogincrements_linear.wheelEvent = lambda event: None
        self.w.jogincrements_angular.wheelEvent = lambda event: None
        self.w.gcode_editor.hide()
        self.w.filemanager.list.setAlternatingRowColors(False)
        self.w.filemanager_usb.list.setAlternatingRowColors(False)
        #set up gcode list
        self.gcodes.setup_list()
        # set up web page viewer
        self.web_view = QWebView()
        self.web_page = QWebPage()
        self.web_page.setLinkDelegationPolicy(QWebPage.DelegateAllLinks)
        self.web_view.setPage(self.web_page)
        self.w.layout_setup.addWidget(self.web_view)

    def init_probe(self):
        probe = INFO.get_error_safe_setting('PROBE', 'USE_PROBE', 'none').lower()
        if probe == 'versaprobe':
            LOG.info("Using Versa Probe")
            from qtvcp.widgets.versa_probe import VersaProbe
            self.probe = VersaProbe()
            self.probe.setObjectName('versaprobe')
        elif probe == 'basicprobe':
            LOG.info("Using Basic Probe")
            from qtvcp.widgets.basic_probe import BasicProbe
            self.probe = BasicProbe()
            self.probe.setObjectName('basicprobe')
        else:
            LOG.info("No valid probe widget specified")
            self.w.btn_probe.hide()
            return
        self.w.probe_layout.addWidget(self.probe)
        self.probe.hal_init()

    def init_vtk(self):
        self.vtkbackplot = VTKBackPlot()
        self.vtkbackplot.setObjectName("vtkbackplot")
        self.w.layout_vtk.addWidget(self.vtkbackplot)

    def init_utils(self):
        from facing import Facing
        self.facing = Facing()
        self.w.layout_facing.addWidget(self.facing)
        from hole_circle import Hole_Circle
        self.hole_circle = Hole_Circle()
        self.w.layout_hole_circle.addWidget(self.hole_circle)
        from calculator import Calculator
        self.calculator = Calculator()
        self.w.layout_calculator.addWidget(self.calculator)

    def processed_focus_event__(self, receiver, event):
        if not self.w.chk_use_virtual.isChecked() or STATUS.is_auto_mode(): return
        if isinstance(receiver, QtWidgets.QLineEdit):
            if not receiver.isReadOnly():
                self.w.stackedWidget_dro.setCurrentIndex(1)
        elif isinstance(receiver, QtWidgets.QTableView):
            self.w.stackedWidget_dro.setCurrentIndex(1)
        elif isinstance(receiver, QtWidgets.QCommonStyle):
            return
    
    def processed_key_event__(self,receiver,event,is_pressed,key,code,shift,cntrl):
        # when typing in MDI, we don't want keybinding to call functions
        # so we catch and process the events directly.
        # We do want ESC, F1 and F2 to call keybinding functions though
        if code not in(QtCore.Qt.Key_Escape,QtCore.Qt.Key_F1 ,QtCore.Qt.Key_F2):
#                    QtCore.Qt.Key_F3,QtCore.Qt.Key_F4,QtCore.Qt.Key_F5):

            # search for the top widget of whatever widget received the event
            # then check if it's one we want the keypress events to go to
            flag = False
            receiver2 = receiver
            while receiver2 is not None and not flag:
                if isinstance(receiver2, QtWidgets.QDialog):
                    flag = True
                    break
                if isinstance(receiver2, QtWidgets.QLineEdit):
                    flag = True
                    break
                if isinstance(receiver2, MDI_WIDGET):
                    flag = True
                    break
                if isinstance(receiver2, GCODE):
                    flag = True
                    break
                if isinstance(receiver2, TOOL_TABLE):
                    flag = True
                    break
                if isinstance(receiver2, OFFSET_VIEW):
                    flag = True
                    break
                receiver2 = receiver2.parent()

            if flag:
                if isinstance(receiver2, GCODE):
                    # if in manual do our keybindings - otherwise
                    # send events to gcode widget
                    if STATUS.is_man_mode() == False:
                        if is_pressed:
                            receiver.keyPressEvent(event)
                            event.accept()
                        return True
                elif is_pressed:
                    receiver.keyPressEvent(event)
                    event.accept()
                    return True
                else:
                    event.accept()
                    return True

        # ok if we got here then try keybindings
        try:
            KEYBIND.call(self,event,is_pressed,shift,cntrl)
            event.accept()
            return True
        except NameError as e:
            if is_pressed:
                LOG.debug('Exception in KEYBINDING: {}'.format (e))
                self.add_status('Exception in KEYBINDING: {}'.format (e))
        except Exception as e:
            if is_pressed:
                LOG.debug('Exception in KEYBINDING:', exc_info=e)
                print ('Error in, or no function for: %s in handler file for-%s'%(KEYBIND.convert(event),key))
        event.accept()
        return True

    #########################
    # CALLBACKS FROM STATUS #
    #########################

    def spindle_pwr_changed(self, data):
        # this calculation assumes the voltage is line to neutral
        # that the current reported by the VFD is total current for all 3 phases
        # and that the synchronous motor spindle has a power factor of 0.9
        power = self.h['spindle_volts'] * self.h['spindle_amps'] * 0.9 # V x I x PF
        amps = "{:1.1f}".format(self.h['spindle_amps'])
        volts = "{:1.1f}".format(self.h['spindle_volts'])
        pwr = "{:1.1f}".format(power)
        self.w.lbl_spindle_amps.setText(amps)
        self.w.lbl_spindle_volts.setText(volts)
        self.w.lbl_spindle_power.setText(pwr)

    def spindle_fault_changed(self, data):
        fault = hex(self.h['spindle_fault'])
        self.w.lbl_spindle_fault.setText(fault)

    def mb_errors_changed(self, data):
        errors = self.h['modbus-errors']
        self.w.lbl_mb_errors.setText(str(errors))

    def dialog_return(self, w, message):
        rtn = message.get('RETURN')
        name = message.get('NAME')
        plate_code = bool(message.get('ID') == '_touchplate_')
        sensor_code = bool(message.get('ID') == '_toolsensor_')
        wait_code = bool(message.get('ID') == '_wait_resume_')
        unhome_code = bool(message.get('ID') == '_unhome_')
        if plate_code and name == 'MESSAGE' and rtn is True:
            self.touchoff('touchplate')
        elif sensor_code and name == 'MESSAGE' and rtn is True:
            self.touchoff('sensor')
        elif wait_code and name == 'MESSAGE':
            self.h['eoffset_clear'] = False
        elif unhome_code and name == 'MESSAGE' and rtn is True:
            ACTION.SET_MACHINE_UNHOMED(-1)

    def user_system_changed(self, data):
        sys = self.system_list[int(data) - 1]
        self.w.offset_table.selectRow(int(data) + 3)
        self.w.actionbutton_rel.setText(sys)

    def metric_mode_changed(self, mode):
        if mode is False:
            self.w.lbl_jog_linear.setText('JOG RATE\nIN/MIN')
            maxvel = float(self.max_linear_velocity) / 25.4
        else:
            self.w.lbl_jog_linear.setText('JOG RATE\nMM/MIN')
            maxvel = float(self.max_linear_velocity)
        self.w.lbl_max_rapid.setText("{:4.0f}".format(maxvel))

    def file_loaded(self, obj, filename):
        if filename is not None:
            self.add_status("Loaded file {}".format(filename))
            self.w.progressBar.setValue(0)
            self.last_loaded_program = filename
            self.w.lbl_runtime.setText("00:00:00")
        else:
            self.add_status("Filename not valid")

    def percent_loaded_changed(self, fraction):
        if fraction <0:
            self.w.progressBar.setValue(0)
            self.w.progressBar.setFormat('PROGRESS')
        else:
            self.w.progressBar.setValue(fraction)
            self.w.progressBar.setFormat('LOADING: {}%'.format(fraction))

    def percent_done_changed(self, fraction):
        self.w.progressBar.setValue(fraction)
        if fraction <0:
            self.w.progressBar.setValue(0)
            self.w.progressBar.setFormat('PROGRESS')
        else:
            self.w.progressBar.setFormat('COMPLETE: {}%'.format(fraction))

    def homed(self, obj, joint):
        i = int(joint)
        axis = INFO.GET_NAME_FROM_JOINT.get(i).lower()
        try:
            widget = self.w["dro_axis_{}".format(axis)]
            widget.setProperty('homed', True)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        except:
            pass

    def all_homed(self, obj):
        self.home_all = True
        self.w.btn_home_all.setText("ALL HOMED")
        if self.first_turnon is True:
            self.first_turnon = False
            if self.w.chk_reload_tool.isChecked():
                command = "M61 Q{}".format(self.reload_tool)
                ACTION.CALL_MDI(command)
            if self.last_loaded_program is not None and self.w.chk_reload_program.isChecked():
                if os.path.isfile(self.last_loaded_program):
                    self.w.cmb_gcode_history.addItem(self.last_loaded_program)
                    self.w.cmb_gcode_history.setCurrentIndex(self.w.cmb_gcode_history.count() - 1)
                    ACTION.OPEN_PROGRAM(self.last_loaded_program)
        ACTION.SET_MANUAL_MODE()
        self.w.manual_mode_button.setChecked(True)

    def not_all_homed(self, obj, list):
        self.home_all = False
        self.w.btn_home_all.setText("HOME ALL")
        for i in INFO.AVAILABLE_JOINTS:
            if str(i) in list:
                axis = INFO.GET_NAME_FROM_JOINT.get(i).lower()
                try:
                    widget = self.w["dro_axis_{}".format(axis)]
                    widget.setProperty('homed', False)
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)
                except:
                    pass

    def hard_limit_tripped(self, obj, tripped, list_of_tripped):
        self.add_status("Hard limits tripped")
        self.w.chk_override_limits.setEnabled(tripped)
        if not tripped:
            self.w.chk_override_limits.setChecked(False)
    
    #######################
    # CALLBACKS FROM FORM #
    #######################

    # main button bar
    def main_tab_changed(self, btn):
        if STATUS.is_auto_mode():
            self.add_status("Cannot switch pages while in AUTO mode")
            self.w.btn_main.setChecked(True)
            return
        index = btn.property("index")
        if index is None: return
        self.w.main_tab_widget.setCurrentIndex(index)
        if index == TAB_SETUP or index == TAB_TOOL:
            self.w.jogging_frame.hide()
        else:
            self.w.jogging_frame.show()
        if index == TAB_FILE:
            self.w.stackedWidget.setCurrentIndex(1)
        elif index == TAB_OFFSETS:
            self.w.stackedWidget.setCurrentIndex(2)
        else:
            self.w.stackedWidget.setCurrentIndex(0)

    # gcode frame
    def cmb_gcode_history_clicked(self):
        if self.w.cmb_gcode_history.currentIndex() == 0: return
        filename = self.w.cmb_gcode_history.currentText().encode('utf-8')
        if filename == self.last_loaded_program:
            self.add_status("Selected program is already loaded")
        else:
            ACTION.OPEN_PROGRAM(filename)

    # program frame
    def btn_start_clicked(self, obj):
        if STATUS.is_auto_running():
            self.add_status("Program is already running")
            return
        self.run_time = 0
        self.w.lbl_runtime.setText("00:00:00")
        if self.start_line <= 1:
            ACTION.RUN(self.start_line)
        else:
            # instantiate run from line preset dialog
            info = '<b>Running From Line: {} <\b>'.format(self.start_line)
            mess = {'NAME':'RUNFROMLINE', 'TITLE':'Preset Dialog', 'ID':'_RUNFROMLINE', 'MESSAGE':info, 'LINE':self.start_line}
            ACTION.CALL_DIALOG(mess)
        self.add_status("Started program from line {}".format(self.start_line))
        self.timer_on = True

    def btn_reload_file_clicked(self):
        if self.last_loaded_program:
            self.w.progressBar.setValue(0)
            self.add_status("Loaded program file {}".format(self.last_loaded_program))
            ACTION.OPEN_PROGRAM(self.last_loaded_program)

    # DRO frame
    def btn_home_all_clicked(self, obj):
        if self.home_all is False:
            ACTION.SET_MACHINE_HOMING(-1)
        else:
        # instantiate dialog box
            info = "Unhome All Axes?"
            mess = {'NAME':'MESSAGE', 'ID':'_unhome_', 'MESSAGE':'UNHOME ALL', 'MORE':info, 'TYPE':'OKCANCEL'}
            ACTION.CALL_DIALOG(mess)

    def btn_home_clicked(self):
        joint = self.w.sender().property('joint')
        axis = INFO.GET_NAME_FROM_JOINT.get(joint).lower()
        if self.w["dro_axis_{}".format(axis)].property('homed') is True:
            ACTION.SET_MACHINE_UNHOMED(joint)
        else:
            ACTION.SET_MACHINE_HOMING(joint)

    # tool frame
    def disable_pause_buttons(self, state):
        self.w.action_pause.setEnabled(not state)
        self.w.action_step.setEnabled(not state)
        if state:
        # set external offsets to lift spindle
            self.h['eoffset_enable'] = self.w.chk_eoffsets.isChecked()
            fval = float(self.w.lineEdit_eoffset_count.text())
            self.h['eoffset_count'] = int(fval)
            self.h['spindle_pause'] = True
        else:
            self.h['eoffset_count'] = 0
            self.h['eoffset_clear'] = True
            self.h['spindle_pause'] = False
        # instantiate warning box
            info = "Wait for spindle at speed signal before resuming"
            mess = {'NAME':'MESSAGE', 'ICON':'WARNING', 'ID':'_wait_resume_', 'MESSAGE':'CAUTION', 'MORE':info, 'TYPE':'OK'}
            ACTION.CALL_DIALOG(mess)
        
    # override frame
    def slow_button_clicked(self, state):
        slider = self.w.sender().property('slider')
        current = self.w[slider].value()
        max = self.w[slider].maximum()
        if state:
            self.w.sender().setText("SLOW")
            self.w[slider].setMaximum(max / self.slow_jog_factor)
            self.w[slider].setValue(current / self.slow_jog_factor)
            self.w[slider].setPageStep(10)
        else:
            self.w.sender().setText("FAST")
            self.w[slider].setMaximum(max * self.slow_jog_factor)
            self.w[slider].setValue(current * self.slow_jog_factor)
            self.w[slider].setPageStep(100)

    def slider_maxv_changed(self, value):
        maxpc = (float(value) / self.max_linear_velocity) * 100
        self.w.lbl_maxv_percent.setText("{:3.0f} %".format(maxpc))

    def slider_rapid_changed(self, value):
        if STATUS.is_metric_mode():
            rapid = (float(value) / 100) * self.max_linear_velocity
        else:
            rapid = (float(value) / 100) * (self.max_linear_velocity / 25.4)
        self.w.lbl_max_rapid.setText("{:4.0f}".format(rapid))

    def btn_maxv_100_clicked(self):
        self.w.slider_maxv_ovr.setValue(self.max_linear_velocity)

    def btn_maxv_50_clicked(self):
        self.w.slider_maxv_ovr.setValue(self.max_linear_velocity / 2)

    # main tab
    def showMachineBounds(self, state):
        self.vtkbackplot.showMachineBounds(state)
        if not state:
            self.vtkbackplot.showMachineLabels(False)
            self.w.btn_machine_labels.setChecked(False)

    def showMachineLabels(self, state):
        if self.w.btn_machine_bounds.isChecked():
            self.vtkbackplot.showMachineLabels(state)
        
    def showProgramBounds(self, state):
        self.vtkbackplot.showProgramBounds(state)
        if not state:
            self.vtkbackplot.showProgramLabels(False)
            self.w.btn_program_labels.setChecked(False)

    def showProgramLabels(self, state):
        if self.w.btn_program_bounds.isChecked():
            self.vtkbackplot.showProgramLabels(state)

    def btn_custom_clicked(self, state):
        if state:
            self.w.widget_custom_buttons.show()
        else:
            self.w.widget_custom_buttons.hide()

    # file tab
    def btn_gcode_edit_clicked(self, state):
        if not STATUS.is_on_and_idle():
            return
        if state:
            self.w.filemanager.hide()
            self.w.widget_file_copy.hide()
            self.w.gcode_editor.show()
            self.w.gcode_editor.editMode()
        else:
            self.w.filemanager.show()
            self.w.widget_file_copy.show()
            self.w.gcode_editor.hide()
            self.w.gcode_editor.readOnlyMode()

    def btn_load_file_clicked(self):
        fname = self.w.filemanager.getCurrentSelected()
        if fname[1] is True:
            self.load_code(fname[0])

    def btn_copy_file_clicked(self):
        if self.w.sender() == self.w.btn_copy_right:
            source = self.w.filemanager_usb.getCurrentSelected()
            target = self.w.filemanager.getCurrentSelected()
        elif self.w.sender() == self.w.btn_copy_left:
            source = self.w.filemanager.getCurrentSelected()
            target = self.w.filemanager_usb.getCurrentSelected()
        else:
            return
        if source[1] is False:
            self.add_status("Specified source is not a file")
            return
        if target[1] is True:
            destination = os.path.join(os.path.dirname(target[0]), os.path.basename(source[0]))
        else:
            destination = os.path.join(target[0], os.path.basename(source[0]))
        try:
            copyfile(source[0], destination)
            self.add_status("Copied file from {} to {}".format(source[0], destination))
        except Exception as e:
            self.add_status("Unable to copy file. %s" %e)

    # offsets tab
    def btn_goto_sensor_clicked(self):
        x = float(self.w.lineEdit_sensor_x.text())
        y = float(self.w.lineEdit_sensor_y.text())
        if not STATUS.is_metric_mode():
            x = x / 25.4
            y = y / 25.4
        ACTION.CALL_MDI("G90")
        ACTION.CALL_MDI_WAIT("G53 G0 Z0")
        command = "G53 G0 X{:3.4f} Y{:3.4f}".format(x, y)
        ACTION.CALL_MDI_WAIT(command, 10)
 
    def btn_ref_laser_clicked(self):
        x = float(self.w.lineEdit_laser_x.text())
        y = float(self.w.lineEdit_laser_y.text())
        if not STATUS.is_metric_mode():
            x = x / 25.4
            y = y / 25.4
        self.add_status("Laser offsets set")
        command = "G10 L20 P0 X{:3.4f} Y{:3.4f}".format(x, y)
        ACTION.CALL_MDI(command)
    
    def btn_ref_camera_clicked(self):
        x = float(self.w.lineEdit_camera_x.text())
        y = float(self.w.lineEdit_camera_y.text())
        if not STATUS.is_metric_mode():
            x = x / 25.4
            y = y / 25.4
        self.add_status("Camera offsets set")
        command = "G10 L20 P0 X{:3.4f} Y{:3.4f}".format(x, y)
        ACTION.CALL_MDI(command)
    
    # tool tab
    def btn_m61_clicked(self):
        checked = self.w.tooloffsetview.get_checked_list()
        if len(checked) > 1:
            self.add_status("Select only 1 tool to load")
        elif checked:
            self.add_status("Loaded tool {}".format(checked[0]))
            ACTION.CALL_MDI("M61 Q{}".format(checked[0]))
        else:
            self.add_status("No tool selected")

    def btn_touchoff_clicked(self):
        if STATUS.get_current_tool() == 0:
            self.add_status("Cannot touchoff with no tool loaded")
            return
        if not STATUS.is_all_homed():
            self.add_status("Must be homed to perform tool touchoff")
            return
        # instantiate dialog box
        sensor = self.w.sender().property('sensor')
        info = "Ensure tooltip is within {} mm of tool sensor and click OK".format(self.w.lineEdit_max_probe.text())
        mess = {'NAME':'MESSAGE', 'ID':sensor, 'MESSAGE':'TOOL TOUCHOFF', 'MORE':info, 'TYPE':'OKCANCEL'}
        ACTION.CALL_DIALOG(mess)
        
    # status tab
    def btn_clear_status_clicked(self):
        STATUS.emit('update-machine-log', None, 'DELETE')

    def btn_save_status_clicked(self):
        text = self.w.machinelog.toPlainText()
        filename = self.w.lbl_clock.text().encode('utf-8')
        filename = 'status_' + filename.replace(' ','_') + '.txt'
        self.add_status("Saving Status file to {}".format(filename))
        with open(filename, 'w') as f:
            f.write(text)

    # camview tab
    def cam_zoom_changed(self, value):
        self.w.camview.scale = float(value) / 10

    def cam_dia_changed(self, value):
        self.w.camview.diameter = value

    def cam_rot_changed(self, value):
        self.w.camview.rotation = float(value) / 10

    # settings tab
    def chk_override_limits_checked(self, state):
        if state:
            print("Override limits set")
            ACTION.SET_LIMITS_OVERRIDE()
        else:
            print("Override limits not set")

    def chk_run_from_line_checked(self, state):
        self.w.btn_start.setText("START\n1") if state else self.w.btn_start.setText("START")

    def chk_alpha_mode_changed(self, state):
        self.vtkbackplot.alphaBlend(state)

    def chk_use_camera_changed(self, state):
        self.w.btn_ref_camera.setEnabled(state)
        self.w.btn_camera.show() if state else self.w.btn_camera.hide()

    def chk_use_sensor_changed(self, state):
        self.w.btn_touch_sensor.setEnabled(state)

    def chk_use_touchplate_changed(self, state):
        self.w.btn_touchplate.setEnabled(state)

    def chk_use_virtual_changed(self, state):
        if not state:
            self.w.stackedWidget_dro.setCurrentIndex(0)

    #####################
    # GENERAL FUNCTIONS #
    #####################
    def load_code(self, fname):
        if fname is None: return
        if fname.endswith(".ngc") or fname.endswith(".py"):
            self.w.cmb_gcode_history.addItem(fname)
            self.w.cmb_gcode_history.setCurrentIndex(self.w.cmb_gcode_history.count() - 1)
            ACTION.OPEN_PROGRAM(fname)
            self.add_status("Loaded program file : {}".format(fname))
            self.w.main_tab_widget.setCurrentIndex(TAB_MAIN)
        elif fname.endswith(".html"):
            try:
                self.web_page.mainFrame().load(QtCore.QUrl.fromLocalFile(fname))
                self.add_status("Loaded HTML file : {}".format(fname))
                self.w.main_tab_widget.setCurrentIndex(TAB_SETUP)
                self.w.stackedWidget.setCurrentIndex(0)
                self.w.btn_setup.setChecked(True)
                self.w.jogging_frame.hide()
            except Exception as e:
                print("Error loading HTML file : {}".format(e))
        else:
            self.add_status("Unknown or invalid filename")

    def disable_spindle_pause(self):
        self.h['eoffset_count'] = 0
        self.h['spindle_pause'] = False
        if self.w.btn_spindle_pause.isChecked():
            self.w.btn_spindle_pause.setChecked(False)

    def touchoff(self, selector):
        if selector == 'touchplate':
            z_offset = float(self.w.lineEdit_touch_height.text())
        elif selector == 'sensor':
            z_offset = float(self.w.lineEdit_sensor_height.text()) - float(self.w.lineEdit_work_height.text())
        else:
            self.add_alarm("Unknown touchoff routine specified")
            return
        self.add_status("Touchoff to {} started".format(selector))
        max_probe = self.w.lineEdit_max_probe.text()
        search_vel = self.w.lineEdit_search_vel.text()
        probe_vel = self.w.lineEdit_probe_vel.text()
        ACTION.CALL_MDI("G21 G49")
        ACTION.CALL_MDI("G10 L20 P0 Z0")
        ACTION.CALL_MDI("G91")
        command = "G38.2 Z-{} F{}".format(max_probe, search_vel)
        if ACTION.CALL_MDI_WAIT(command, 10) == -1:
            ACTION.CALL_MDI("G90")
            return
        if ACTION.CALL_MDI_WAIT("G1 Z4.0"):
            ACTION.CALL_MDI("G90")
            return
        ACTION.CALL_MDI("G4 P0.5")
        command = "G38.2 Z-4.4 F{}".format(probe_vel)
        if ACTION.CALL_MDI_WAIT(command, 10) == -1:
            ACTION.CALL_MDI("G90")
            return
        command = "G10 L20 P0 Z{}".format(z_offset)
        ACTION.CALL_MDI_WAIT(command)
        command = "G1 Z10 F{}".format(search_vel)
        ACTION.CALL_MDI_WAIT(command)
        ACTION.CALL_MDI("G90")

    def kb_jog(self, state, joint, direction, fast = False, linear = True):
        if not STATUS.is_man_mode() or not STATUS.machine_is_on():
            self.add_status('Machine must be ON and in Manual mode to jog')
            return
        if linear:
            distance = STATUS.get_jog_increment()
            rate = STATUS.get_jograte()/60
        else:
            distance = STATUS.get_jog_increment_angular()
            rate = STATUS.get_jograte_angular()/60
        if state:
            if fast:
                rate = rate * 2
            ACTION.JOG(joint, direction, rate, distance)
        else:
            ACTION.JOG(joint, 0, 0, 0)

    def add_status(self, message):
        self.w.lbl_statusbar.setText(message)
        STATUS.emit('update-machine-log', message, 'TIME')

    def enable_auto(self, state):
        if state is True:
            self.w.jogging_frame.hide()
            self.w.btn_main.setChecked(True)
            self.w.main_tab_widget.setCurrentIndex(TAB_MAIN)
            self.w.stackedWidget.setCurrentIndex(0)
            self.w.stackedWidget_dro.setCurrentIndex(0)
        else:
            self.w.jogging_frame.show()

    def enable_onoff(self, state):
        if state:
            self.add_status("Machine ON")
        else:
            self.add_status("Machine OFF")
        self.w.btn_spindle_pause.setChecked(False)
        self.h['eoffset_count'] = 0
        for widget in self.onoff_list:
            self.w[widget].setEnabled(state)

    def set_start_line(self, line):
        if self.w.chk_run_from_line.isChecked():
            self.start_line = line
            self.w.btn_start.setText("START\n{}".format(self.start_line))
        else:
            self.start_line = 1

    def use_keyboard(self):
        if self.w.chk_use_keyboard.isChecked():
            return True
        else:
            self.add_status('Keyboard shortcuts are disabled')
            return False

    def update_rpm(self, speed):
        if int(speed) == 0:
            in_range = True
            at_speed = True
        else:
            in_range = (self.min_spindle_rpm <= int(speed) <= self.max_spindle_rpm)
            at_speed = self.h['led_atspeed']
        widget = self.w.lbl_spindle_set
        widget.setProperty('in_range', in_range)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget = self.w.status_rpm
        widget.setProperty('at_speed', at_speed)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def update_runtimer(self):
        if self.timer_on is False or STATUS.is_auto_paused(): return
        self.time_tenths += 1
        if self.time_tenths == 10:
            self.time_tenths = 0
            self.run_time += 1
            hours, remainder = divmod(self.run_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.w.lbl_runtime.setText("{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds))

    def stop_timer(self):
        self.timer_on = False
        if STATUS.is_auto_mode():
            self.add_status("Run timer stopped at {}".format(self.w.lbl_runtime.text()))

    #####################
    # KEY BINDING CALLS #
    #####################

    def on_keycall_ESTOP(self,event,state,shift,cntrl):
        if state:
            ACTION.SET_ESTOP_STATE(True)

    def on_keycall_POWER(self,event,state,shift,cntrl):
        if state:
            ACTION.SET_MACHINE_STATE(False)

    def on_keycall_ABORT(self,event,state,shift,cntrl):
        if state:
            ACTION.ABORT()

    def on_keycall_HOME(self,event,state,shift,cntrl):
        if state and not STATUS.is_all_homed() and self.use_keyboard():
            ACTION.SET_MACHINE_HOMING(-1)

    def on_keycall_pause(self,event,state,shift,cntrl):
        if state and STATUS.is_auto_mode() and self.use_keyboard():
            ACTION.PAUSE()

    def on_keycall_XPOS(self,event,state,shift,cntrl):
        if self.use_keyboard():
            self.kb_jog(state, 0, 1, shift)

    def on_keycall_XNEG(self,event,state,shift,cntrl):
        if self.use_keyboard():
            self.kb_jog(state, 0, -1, shift)

    def on_keycall_YPOS(self,event,state,shift,cntrl):
        if self.use_keyboard():
            self.kb_jog(state, 1, 1, shift)

    def on_keycall_YNEG(self,event,state,shift,cntrl):
        if self.use_keyboard():
            self.kb_jog(state, 1, -1, shift)

    def on_keycall_ZPOS(self,event,state,shift,cntrl):
        if self.use_keyboard():
            self.kb_jog(state, 2, 1, shift)

    def on_keycall_ZNEG(self,event,state,shift,cntrl):
        if self.use_keyboard():
            self.kb_jog(state, 2, -1, shift)
    
    def on_keycall_APOS(self,event,state,shift,cntrl):
        if self.use_keyboard():
            self.kb_jog(state, 3, 1, shift, False)

    def on_keycall_ANEG(self,event,state,shift,cntrl):
        if self.use_keyboard():
            self.kb_jog(state, 3, -1, shift, False)

    def on_keycall_F12(self,event,state,shift,cntrl):
        if state:
            self.styleeditor.load_dialog()

    ##############################
    # required class boiler code #
    ##############################
    def __getitem__(self, item):
        return getattr(self, item)

    def __setitem__(self, item, value):
        return setattr(self, item, value)

################################
# required handler boiler code #
################################

def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]
