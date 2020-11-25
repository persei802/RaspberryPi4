#!/usr/bin/env python
import os
from math import cos, sin, radians
from operator import add
from collections import OrderedDict
import linuxcnc
from PyQt5.QtGui import QColor
from PyQt5.QtCore import pyqtProperty
import vtk

# Fix polygons not drawing correctly on some GPU
# https://stackoverflow.com/questions/51357630/vtk-rendering-not-working-as-expected-inside-pyqt?rq=1
import vtk.qt
vtk.qt.QVTKRWIBase = "QGLWidget"
# Fix end

from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtk.util.colors import tomato, yellow, mint
from qtvcp.core import Info, Status, Tool
from qtvcp.widgets.tool_offsetview import ToolOffsetView as TOOL_TABLE
from base_canon import StatCanon
from base_backplot import BaseBackPlot

INFO = Info()
STATUS = Status()
TOOL = Tool()
INIFILE = INFO.INIPATH
BASE = BaseBackPlot(INIFILE)
MACHINE_UNITS = INFO.get_error_safe_setting("TRAJ", "LINEAR_UNITS", "metric")
LATHE = INFO.get_error_safe_setting("DISPLAY", "LATHE", False)
COLOR_MAP = {
    'traverse': (188, 252, 201, 75),
    'arcfeed': (255, 255, 255, 128),
    'feed': (255, 255, 255, 84),
    'dwell': (100, 100, 100, 255),
    'user': (100, 100, 100, 255)}


class PathActor(vtk.vtkActor):
    def __init__(self):
        super(PathActor, self).__init__()
        self.origin_index = None
        self.origin_cords = None
        self.units = MACHINE_UNITS
        self.lathe = LATHE

        if self.units in ("mm", "metric"):
            self.length = 25.0
        else:
            self.length = 1.0
        self.axes = Axes()
        self.axes_actor = self.axes.get_actor()
        if self.lathe is True:
            self.axes_actor.SetTotalLength(self.length, 0, self.length)
        else:
            self.axes_actor.SetTotalLength(self.length, self.length, self.length)

        # Create a vtkUnsignedCharArray container and store the colors in it
        self.colors = vtk.vtkUnsignedCharArray()
        self.colors.SetNumberOfComponents(4)
        self.points = vtk.vtkPoints()
        self.lines = vtk.vtkCellArray()
        self.poly_data = vtk.vtkPolyData()
        self.data_mapper = vtk.vtkPolyDataMapper()

    def set_origin_index(self, index):
        self.origin_index = index

    def get_origin_index(self):
        return self.origin_index

    def set_orgin_coords(self, *cords):
        self.origin_cords = cords

    def get_origin_coords(self):
        return self.origin_cords

    def get_axes(self):
        return self.axes_actor


class VTKCanon(StatCanon):
    def __init__(self, colors=COLOR_MAP, *args, **kwargs):
        super(VTKCanon, self).__init__(*args, **kwargs)
        self.units = MACHINE_UNITS
        self.index_map = dict()
        self.index_map[1] = 540
        self.index_map[2] = 550
        self.index_map[3] = 560
        self.index_map[4] = 570
        self.index_map[5] = 580
        self.index_map[6] = 590
        self.index_map[7] = 591
        self.index_map[8] = 592
        self.index_map[9] = 593
        self.path_colors = colors
        self.path_actors = OrderedDict()
        self.path_points = OrderedDict()
        origin = 540
        self.path_actors[origin] = PathActor()
        self.path_points[origin] = list()
        self.origin = origin
        self.previous_origin = origin
        self.ignore_next = False  # hacky way to ignore the second point next to a offset change

    def rotate_and_translate(self, x, y, z, a, b, c, u, v, w):
        # override function to handle it in vtk back plot
        return x, y, z, a, b, c, u, v, w

    def set_g5x_offset(self, index, x, y, z, a, b, c, u, v, w):
        origin = self.index_map[index]
        if origin not in self.path_actors.keys():
            self.path_actors[origin] = PathActor()
            self.path_points[origin] = list()
            self.previous_origin = self.origin
            self.origin = origin

    def add_path_point(self, line_type, start_point, end_point):
        if self.ignore_next is True:
            self.ignore_next = False
            return

        if self.previous_origin != self.origin:
            self.previous_origin = self.origin
            self.ignore_next = True
            return
        path_points = self.path_points.get(self.origin)

        if self.units in ("mm", "metric"):
            start_point_list = list()
            for point in end_point:
                point *= 25.4
                start_point_list.append(point)

            end_point_list = list()
            for point in end_point:
                point *= 25.4
                end_point_list.append(point)

            line = list()
            line.append(start_point_list)
            line.append(end_point_list)
            path_points.append((line_type, line))

        else:
            line = list()
            line.append(start_point)
            line.append(end_point)
            path_points.append((line_type, line))

    def draw_lines(self):
        for origin, data in self.path_points.items():
            path_actor = self.path_actors.get(origin)
            index = 0
            end_point = None
            last_line_type = None
            for line_type, line_data in data:
                start_point = line_data[0]
                end_point = line_data[1]
                last_line_type = line_type
                path_actor.points.InsertNextPoint(start_point[:3])
                path_actor.colors.InsertNextTypedTuple(self.path_colors[line_type])
                line = vtk.vtkLine()
                line.GetPointIds().SetId(0, index)
                line.GetPointIds().SetId(1, index + 1)
                path_actor.lines.InsertNextCell(line)
                index += 1

            if end_point:
                path_actor.points.InsertNextPoint(end_point[:3])
                path_actor.colors.InsertNextTypedTuple(self.path_colors[last_line_type])
                line = vtk.vtkLine()
                line.GetPointIds().SetId(0, index - 1)
                line.GetPointIds().SetId(1, index)
                path_actor.lines.InsertNextCell(line)
            # free up memory, lots of it for big files
            self.path_points[self.origin] = list()
            path_actor.poly_data.SetPoints(path_actor.points)
            path_actor.poly_data.SetLines(path_actor.lines)
            path_actor.poly_data.GetCellData().SetScalars(path_actor.colors)
            path_actor.data_mapper.SetInputData(path_actor.poly_data)
            path_actor.data_mapper.Update()
            path_actor.SetMapper(path_actor.data_mapper)

    def get_path_actors(self):
        return self.path_actors


#class VTKBackPlot(QVTKRenderWindowInteractor, VCPWidget, BaseBackPlot):
class VTKBackPlot(QVTKRenderWindowInteractor, BaseBackPlot):
    def __init__(self, parent=None):
        super(VTKBackPlot, self).__init__(parent)

        self.parent = parent
        self.lathe = LATHE
        self.canon_class = VTKCanon

        self.current_position = None
        file_name = INFO.PARAMETER_FILE
        self.parameter_file = None
        if file_name:
            self.parameter_file = os.path.join(os.path.dirname(os.path.realpath(file_name)), file_name)
        # Todo: get active part

        self.g5x_index = STATUS.stat.g5x_index
        self.index_map = dict()
        self.index_map[1] = 540
        self.index_map[2] = 550
        self.index_map[3] = 560
        self.index_map[4] = 570
        self.index_map[5] = 580
        self.index_map[6] = 590
        self.index_map[7] = 591
        self.index_map[8] = 592
        self.index_map[9] = 593
        self.origin_map = dict()

        for k, v in self.index_map.items():
            self.origin_map[v] = k
        self.g5x_offset = STATUS.stat.g5x_offset
        self.g92_offset = STATUS.stat.g92_offset
        self.rotation_offset = STATUS.stat.rotation_xy

        self.spindle_position = (0.0, 0.0, 0.0)
        self.spindle_rotation = (0.0, 0.0, 0.0)
        self.tooltip_position = (0.0, 0.0, 0.0)

        self.tool_no = 0
        self.tool_keys = ['id', 'pocket',
                          'xoffset', 'yoffset', 'zoffset',
                          'aoffset', 'boffset', 'coffset',
                          'uoffset', 'voffset', 'woffset',
                          'diameter', 'frontangle', 'backangle', 'orientation']
        self.units = MACHINE_UNITS
        self.axis = STATUS.stat.axis
        self.camera = vtk.vtkCamera()
        self.camera.ParallelProjectionOn()
        self.clipping_range_near = 0.01
        self.clipping_range_far = 10.0
        units = INFO.get_error_safe_setting("TRAJ", "LINEAR_UNITS", "mm")
        if units in ["in", "inch", "inchs"]:
            self.clipping_range_near = 0.001
            self.clipping_range_far = 100.0
        elif units in ["mm", "metric"]:
            self.clipping_range_near = 0.01
            self.clipping_range_far = 10000.0

        self.camera.SetClippingRange(self.clipping_range_near, self.clipping_range_far)
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetActiveCamera(self.camera)
        self.renderer_window = self.GetRenderWindow()
        self.renderer_window.AddRenderer(self.renderer)
        self.interactor = self.renderer_window.GetInteractor()
        self.interactor.SetInteractorStyle(None)
        self.interactor.SetRenderWindow(self.renderer_window)
        self.machine = Machine(self.axis)
        self.machine_actor = self.machine.get_actor()
        self.machine_actor.SetCamera(self.camera)
        self.axes = Axes()
        self.axes_actor = self.axes.get_actor()
        transform = vtk.vtkTransform()
        transform.Translate(*self.g5x_offset[:3])
        transform.RotateZ(self.rotation_offset)
#        self.axes_actor.SetUserTransform(transform)
        self.path_cache = PathCache(self.tooltip_position)
        self.path_cache_actor = self.path_cache.get_actor()
        self.tool = Tool(self.get_tool_array())
        self.tool_actor = self.tool.get_actor()
        self.offset_axes = OrderedDict()
        self.extents = OrderedDict()
        self.show_extents = bool()
        self.canon = self.canon_class()
        self.path_actors = self.canon.get_path_actors()

        for origin, actor in self.path_actors.items():
            index = self.origin_map[origin]
            actor_position = self.g5x_offset
            actor_transform = vtk.vtkTransform()
            actor_transform.Translate(*actor_position[:3])
            actor_transform.RotateWXYZ(*actor_position[5:9])
            actor.SetUserTransform(actor_transform)
            extents = PathBoundaries(self.camera, actor)
            extents_actor = extents.get_actor()
            axes = actor.get_axes()
            self.offset_axes[origin] = axes
            self.extents[origin] = extents_actor
            self.renderer.AddActor(axes)
            self.renderer.AddActor(extents_actor)
            self.renderer.AddActor(actor)
        self.renderer.AddActor(self.tool_actor)
        self.renderer.AddActor(self.machine_actor)
        self.renderer.AddActor(self.axes_actor)
        self.renderer.AddActor(self.path_cache_actor)
        self.renderer.ResetCamera()
        self.interactor.AddObserver("LeftButtonPressEvent", self.button_event)
        self.interactor.AddObserver("LeftButtonReleaseEvent", self.button_event)
        self.interactor.AddObserver("MiddleButtonPressEvent", self.button_event)
        self.interactor.AddObserver("MiddleButtonReleaseEvent", self.button_event)
        self.interactor.AddObserver("RightButtonPressEvent", self.button_event)
        self.interactor.AddObserver("RightButtonReleaseEvent", self.button_event)
        self.interactor.AddObserver("MouseMoveEvent", self.mouse_move)
        self.interactor.AddObserver("KeyPressEvent", self.keypress)
        self.interactor.AddObserver("MouseWheelForwardEvent", self.mouse_scroll_forward)
        self.interactor.AddObserver("MouseWheelBackwardEvent", self.mouse_scroll_backward)
        self.interactor.Initialize()
        self.renderer_window.Render()
#        self.interactor.Start()
        # background colours
        self._background_color = QColor(0, 0, 0, 255)
        self._background_color2 = QColor(30, 30, 30, 255)

        self.delay = 0
        STATUS.connect('file-loaded', lambda w, filename: self.load_program(filename))
        STATUS.connect('motion-mode-changed', lambda w, mode: self.motion_type(mode))
        STATUS.connect('user-system-changed', lambda w, data: self.update_g5x_index(data))
        STATUS.connect('periodic', self.periodic_check)
        STATUS.connect('tool-in-spindle-changed', lambda w, tool: self.update_tool(tool))

        self.line = None
        self._last_filename = str()

        # Add the observers to watch for particular events. These invoke
        # Python functions.
        self.rotating = 0
        self.panning = 0
        self.zooming = 0
        self.pan_mode = True

        if self.lathe is True:
            self.setViewXZ()

        # view settings
        self.showProgramBounds(True)
        self.showMachineBounds(True)
        self.setViewP()

    # Handle the mouse button events.
    def button_event(self, obj, event):
        if event == "LeftButtonPressEvent":
            if self.pan_mode is True:
                self.panning = 1
            else:
                self.rotating = 1

        elif event == "LeftButtonReleaseEvent":
            if self.pan_mode is True:
                self.panning = 0
            else:
                self.rotating = 0

        elif event == "RightButtonPressEvent":
            if self.pan_mode is True:
                self.rotating = 1
            else:
                self.panning = 1

        elif event == "RightButtonReleaseEvent":
            if self.pan_mode is True:
                self.rotating = 0
            else:
                self.panning = 0

        elif event == "MiddleButtonPressEvent":
            self.zooming = 1
        elif event == "MiddleButtonReleaseEvent":
            self.zooming = 0

    def mouse_scroll_backward(self, obj, event):
        self.zoomOut()

    def mouse_scroll_forward(self, obj, event):
        self.zoomIn()

    # General high-level logic
    def mouse_move(self, obj, event):
        lastXYpos = self.interactor.GetLastEventPosition()
        lastX = lastXYpos[0]
        lastY = lastXYpos[1]
        xypos = self.interactor.GetEventPosition()
        x = xypos[0]
        y = xypos[1]
        center = self.renderer_window.GetSize()
        centerX = center[0] / 2.0
        centerY = center[1] / 2.0

        if self.rotating:
            if self.lathe is True:
                self.pan(self.renderer, self.camera, x, y, lastX, lastY, centerX, centerY)
            else:   
                self.rotate(self.renderer, self.camera, x, y, lastX, lastY, centerX, centerY)
        elif self.panning:
            self.pan(self.renderer, self.camera, x, y, lastX, lastY, centerX, centerY)
        elif self.zooming:
            self.dolly(self.renderer, self.camera, x, y, lastX, lastY, centerX, centerY)

    def keypress(self, obj, event):
        key = obj.GetKeySym()
        if key == "w":
            self.wireframe()
        elif key == "s":
            self.surface()

    # Routines that translate the events into camera motions.
    # This one is associated with the left mouse button. It translates x
    # and y relative motions into camera azimuth and elevation commands.
    def rotate(self, renderer, camera, x, y, lastX, lastY, centerX, centerY):
        camera.Azimuth(lastX - x)
        camera.Elevation(lastY - y)
        camera.OrthogonalizeViewUp()
        camera.SetClippingRange(self.clipping_range_near, self.clipping_range_far)
        self.renderer_window.Render()
        # self.renderer.ResetCamera()
        self.interactor.ReInitialize()

    # Pan translates x-y motion into translation of the focal point and
    # position.
    def pan(self, renderer, camera, x, y, lastX, lastY, centerX, centerY):
        FPoint = camera.GetFocalPoint()
        FPoint0 = FPoint[0]
        FPoint1 = FPoint[1]
        FPoint2 = FPoint[2]
        PPoint = camera.GetPosition()
        PPoint0 = PPoint[0]
        PPoint1 = PPoint[1]
        PPoint2 = PPoint[2]
        renderer.SetWorldPoint(FPoint0, FPoint1, FPoint2, 1.0)
        renderer.WorldToDisplay()
        DPoint = renderer.GetDisplayPoint()
        focalDepth = DPoint[2]
        APoint0 = centerX + (x - lastX)
        APoint1 = centerY + (y - lastY)
        renderer.SetDisplayPoint(APoint0, APoint1, focalDepth)
        renderer.DisplayToWorld()
        RPoint = renderer.GetWorldPoint()
        RPoint0 = RPoint[0]
        RPoint1 = RPoint[1]
        RPoint2 = RPoint[2]
        RPoint3 = RPoint[3]

        if RPoint3 != 0.0:
            RPoint0 = RPoint0 / RPoint3
            RPoint1 = RPoint1 / RPoint3
            RPoint2 = RPoint2 / RPoint3

        camera.SetFocalPoint((FPoint0 - RPoint0) / 1.0 + FPoint0,
                             (FPoint1 - RPoint1) / 1.0 + FPoint1,
                             (FPoint2 - RPoint2) / 1.0 + FPoint2)

        camera.SetPosition((FPoint0 - RPoint0) / 1.0 + PPoint0,
                           (FPoint1 - RPoint1) / 1.0 + PPoint1,
                           (FPoint2 - RPoint2) / 1.0 + PPoint2)

        self.renderer_window.Render()

    # Dolly converts y-motion into a camera dolly commands.
    def dolly(self, renderer, camera, x, y, lastX, lastY, centerX, centerY):
        dollyFactor = pow(1.02, (0.5 * (y - lastY)))
        if camera.GetParallelProjection():
            parallelScale = camera.GetParallelScale() * dollyFactor
            camera.SetParallelScale(parallelScale)
        else:
            camera.Dolly(dollyFactor)
            renderer.ResetCameraClippingRange()

        self.renderer_window.Render()

    # Wireframe sets the representation of all actors to wireframe.
    def wireframe(self):
        actors = self.renderer.GetActors()
        actors.InitTraversal()
        actor = actors.GetNextItem()
        while actor:
            actor.GetProperty().SetRepresentationToWireframe()
            actor = actors.GetNextItem()
        self.renderer_window.Render()

    # Surface sets the representation of all actors to surface.
    def surface(self):
        actors = self.renderer.GetActors()
        actors.InitTraversal()
        actor = actors.GetNextItem()
        while actor:
            actor.GetProperty().SetRepresentationToSurface()
            actor = actors.GetNextItem()
        self.renderer_window.Render()

    def tlo(self, tlo):
        pass

    def load_program(self, fname=None):
        for origin, actor in self.path_actors.items():
            axes = actor.get_axes()
            extents = self.extents[origin]
            self.renderer.RemoveActor(axes)
            self.renderer.RemoveActor(actor)
            self.renderer.RemoveActor(extents)
        self.path_actors.clear()
        self.offset_axes.clear()
        self.extents.clear()

        if fname:
            self.load(fname)
        if self.canon is None: return
        self.canon.draw_lines()
        self.axes_actor = self.axes.get_actor()
        self.path_actors = self.canon.get_path_actors()
        self.renderer.AddActor(self.axes_actor)

        for origin, actor in self.path_actors.items():
            axes = actor.get_axes()
            index = self.origin_map[origin]
            path_position = self.g5x_offset
            path_transform = vtk.vtkTransform()
            path_transform.Translate(*path_position[:3])
            path_transform.RotateWXYZ(*path_position[5:9])
            axes.SetUserTransform(path_transform)
            actor.SetUserTransform(path_transform)
            extents = PathBoundaries(self.camera, actor)
            extents_actor = extents.get_actor()

            if self.show_extents:
                extents_actor.XAxisVisibilityOn()
                extents_actor.YAxisVisibilityOn()
                extents_actor.ZAxisVisibilityOn()
            else:
                extents_actor.XAxisVisibilityOff()
                extents_actor.YAxisVisibilityOff()
                extents_actor.ZAxisVisibilityOff()

            self.renderer.AddActor(axes)
            self.renderer.AddActor(extents_actor)
            self.renderer.AddActor(actor)
            self.offset_axes[origin] = axes
            self.extents[origin] = extents_actor
        self.update_render()

    def motion_type(self, value):
        if value == linuxcnc.MOTION_TYPE_TOOLCHANGE:
            self.update_tool()

    def update_position(self, position):  # the tool movement
        self.spindle_position = position[:3]
        self.spindle_rotation = position[3:6]
        tool_transform = vtk.vtkTransform()
        tool_transform.Translate(*self.spindle_position)
        tool_transform.RotateX(-self.spindle_rotation[0])
        tool_transform.RotateY(-self.spindle_rotation[1])
        tool_transform.RotateZ(-self.spindle_rotation[2])
        self.tool_actor.SetUserTransform(tool_transform)
        tlo = TOOL.GET_TOOL_INFO(self.tool_no)
        self.tooltip_position = [pos - tlo for pos, tlo in zip(self.spindle_position, tlo[2:5])]
        self.path_cache.add_line_point(self.tooltip_position)
        self.update_render()

    def update_g5x_offset(self):
        offset = self.g5x_offset
#        transform = vtk.vtkTransform()
#        transform.Translate(*offset[:3])
#        transform.RotateWXYZ(*offset[5:9])
#        self.axes_actor.SetUserTransform(transform)
        for origin, actor in self.path_actors.items():
            # path_offset = [n - o for n, o in zip(position[:3], self.original_g5x_offset[:3])]
            path_index = self.origin_map[origin]
            old_extents = self.extents[origin]
            self.renderer.RemoveActor(old_extents)
            axes = actor.get_axes()

            if path_index == self.g5x_index:
                path_transform = vtk.vtkTransform()
                path_transform.Translate(*offset[:3])
                path_transform.RotateWXYZ(*offset[5:9])
                axes.SetUserTransform(path_transform)
                actor.SetUserTransform(path_transform)
            extents = PathBoundaries(self.camera, actor)
            extents_actor = extents.get_actor()

            if self.show_extents:
                extents_actor.XAxisVisibilityOn()
                extents_actor.YAxisVisibilityOn()
                extents_actor.ZAxisVisibilityOn()
            else:
                extents_actor.XAxisVisibilityOff()
                extents_actor.YAxisVisibilityOff()
                extents_actor.ZAxisVisibilityOff()
            self.renderer.AddActor(extents_actor)
            self.extents[origin] = extents_actor
        self.interactor.ReInitialize()
        self.update_render()

    def update_g5x_index(self, index):
        self.g5x_index = int(index)
#        position = STATUS.stat.g5x_offset
#        position = self.g5x_offset
#        transform = vtk.vtkTransform()
#        transform.Translate(*position[:3])
#        transform.RotateWXYZ(*position[5:9])
#        self.axes_actor.SetUserTransform(transform)
#        self.interactor.ReInitialize()
#        self.update_render()

    def update_g92_offset(self):
        if STATUS.is_mdi_mode() or STATUS.is_auto_mode():
            path_offset = list(map(add, self.g92_offset, self.original_g92_offset))

            for origin, actor in self.path_actors.items():
                # determine change in g92 offset since path was drawn
                index = self.origin_map[origin] - 1
                new_path_position = list(map(add, self.g5x_offset[:9], path_offset))
                axes = actor.get_axes()
                path_transform = vtk.vtkTransform()
                path_transform.Translate(*new_path_position[:3])
                self.axes_actor.SetUserTransform(path_transform)
                axes.SetUserTransform(path_transform)
                actor.SetUserTransform(path_transform)
                extents = PathBoundaries(self.camera, actor)
                extents_actor = extents.get_actor()
                if self.show_extents:
                    extents_actor.XAxisVisibilityOn()
                    extents_actor.YAxisVisibilityOn()
                    extents_actor.ZAxisVisibilityOn()
                else:
                    extents_actor.XAxisVisibilityOff()
                    extents_actor.YAxisVisibilityOff()
                    extents_actor.ZAxisVisibilityOff()
                self.renderer.AddActor(extents_actor)
                self.extents[origin] = extents_actor
            self.interactor.ReInitialize()
            self.update_render()

    def update_tool(self, tool):
        self.tool_no = tool
        self.renderer.RemoveActor(self.tool_actor)
        self.tool = Tool(self.get_tool_array())
        self.tool_actor = self.tool.get_actor()
        tool_transform = vtk.vtkTransform()
        tool_transform.Translate(*self.spindle_position)
        tool_transform.RotateX(-self.spindle_rotation[0])
        tool_transform.RotateY(-self.spindle_rotation[1])
        tool_transform.RotateZ(-self.spindle_rotation[2])
        self.tool_actor.SetUserTransform(tool_transform)
        self.renderer.AddActor(self.tool_actor)
        self.update_render()

    def update_render(self):
#        self.GetRenderWindow().Render()
        self.renderer_window.Render()

    def get_tool_array(self):
        tool_array = {}
        array = TOOL.GET_TOOL_INFO(self.tool_no)
        for i, val in enumerate(self.tool_keys):
            tool_array[val] = array[i]
        return tool_array

    def periodic_check(self, w):
        STATUS.stat.poll()
        position = STATUS.stat.actual_position
        if position != self.current_position:
            self.current_position = position
            self.update_position(position)
        if self.delay < 9:
            self.delay += 1
        else:
            self.delay = 0
            g5x_offset = STATUS.stat.g5x_offset
            g92_offset = STATUS.stat.g92_offset
            if g5x_offset != self.g5x_offset:
                self.g5x_offset = g5x_offset
                self.update_g5x_offset()
            if g92_offset != self.g92_offset:
                self.g92_offset = g92_offset
                self.update_g92_offset()
        return True

    def setViewOrtho(self):
        self.camera.ParallelProjectionOn()
        # self.renderer.ResetCamera()
        self.interactor.ReInitialize()

    def setViewPersp(self):
        self.camera.ParallelProjectionOff()
        # self.renderer.ResetCamera()
        self.interactor.ReInitialize()

    def setViewP(self):
        self.camera.SetPosition(1, -1, 1)
        self.camera.SetViewUp(0, 0, 1)
        self.camera.SetFocalPoint(0, 0, 0)
        self.renderer.ResetCamera()
        self.camera.Zoom(1.1)
        self.interactor.ReInitialize()

    def setViewX(self):
        self.camera.SetPosition(1, 0, 0)
        self.camera.SetViewUp(0, 0, 1)
        self.camera.SetFocalPoint(0, 0, 0)
        self.renderer.ResetCamera()
        # FIXME ugly hack
        self.camera.Zoom(1.5)
        self.interactor.ReInitialize()

    def setViewXZ(self):
        self.camera.SetPosition(0, -1, 0)
        self.camera.SetViewUp(-1, 0, 0)
        self.camera.SetFocalPoint(0, 0, 0)
        self.renderer.ResetCamera()
        # FIXME ugly hack
        self.camera.Zoom(1.5)
        self.interactor.ReInitialize()

    def setViewY(self):
        self.camera.SetPosition(0, -1, 0)
        self.camera.SetViewUp(0, 0, 1)
        self.camera.SetFocalPoint(0, 0, 0)
        self.renderer.ResetCamera()
        # FIXME ugly hack
        self.camera.Zoom(1.5)
        self.interactor.ReInitialize()

    def setViewZ(self):
        self.camera.SetPosition(0, 0, 1)
        self.camera.SetViewUp(0, 1, 0)
        self.camera.SetFocalPoint(0, 0, 0)
        self.renderer.ResetCamera()
        # FIXME ugly hack
        self.camera.Zoom(2)
        self.interactor.ReInitialize()

    def printView(self):
        fp = self.camera.GetFocalPoint()
        p = self.camera.GetPosition()
        print('position {}'.format(p))
        # dist = math.sqrt( (p[0]-fp[0])**2 + (p[1]-fp[1])**2 + (p[2]-fp[2])**2 )
        # print(dist)
        # self.camera.SetPosition(10, -40, -1)
        # self.camera.SetViewUp(0.0, 1.0, 0.0)
        # self.renderer.ResetCamera()
        vu = self.camera.GetViewUp()
        d = self.camera.GetDistance()
        print('distance {}'.format(d))
        # self.interactor.ReInitialize()

    def setViewZ2(self):
        self.camera.SetPosition(0, 0, 1)
        self.camera.SetViewUp(1, 0, 0)
        self.camera.SetFocalPoint(0, 0, 0)
        self.renderer.ResetCamera()
        self.interactor.ReInitialize()

    def setViewMachine(self):
        self.machine_actor.SetCamera(self.camera)
        self.renderer.ResetCamera()
        self.interactor.ReInitialize()

    def setViewPath(self):
        position = self.g5x_offset
        self.camera.SetViewUp(0, 0, 1)
        self.camera.SetFocalPoint(position[0],
                                  position[1],
                                  position[2])
        self.camera.SetPosition(position[0] + 1000,
                                position[1] - 1000,
                                position[2] + 1000)
        self.camera.Zoom(1.0)
        self.interactor.ReInitialize()

    def clearLivePlot(self):
        self.renderer.RemoveActor(self.path_cache_actor)
        self.path_cache = PathCache(self.tooltip_position)
        self.path_cache_actor = self.path_cache.get_actor()
        self.renderer.AddActor(self.path_cache_actor)
        self.update_render()

    def enable_panning(self, enabled):
        self.pan_mode = enabled

    def zoomIn(self):
        camera = self.camera
        if camera.GetParallelProjection():
            parallelScale = camera.GetParallelScale() * 0.9
            camera.SetParallelScale(parallelScale)
        else:
            self.renderer.ResetCameraClippingRange()
            camera.Zoom(0.9)
        self.renderer_window.Render()

    def zoomOut(self):
        camera = self.camera
        if camera.GetParallelProjection():
            parallelScale = camera.GetParallelScale() * 1.1
            camera.SetParallelScale(parallelScale)
        else:
            self.renderer.ResetCameraClippingRange()
            camera.Zoom(1.1)
        self.renderer_window.Render()

    def alphaBlend(self, alpha):
        pass

    def showProgramBounds(self, show):
        self.show_extents = show
        PathBoundaries.show_program_bounds = show
        for origin, actor in self.path_actors.items():
            extents = self.extents[origin]
            if extents is not None:
                if show:
                    extents.XAxisVisibilityOn()
                    extents.YAxisVisibilityOn()
                    extents.ZAxisVisibilityOn()
                else:
                    extents.XAxisVisibilityOff()
                    extents.YAxisVisibilityOff()
                    extents.ZAxisVisibilityOff()
        self.update_render()

    def showMachineBounds(self, show):
        if show:
            self.machine_actor.XAxisVisibilityOn()
            self.machine_actor.YAxisVisibilityOn()
            self.machine_actor.ZAxisVisibilityOn()
        else:
            self.machine_actor.XAxisVisibilityOff()
            self.machine_actor.YAxisVisibilityOff()
            self.machine_actor.ZAxisVisibilityOff()
        self.update_render()

    @pyqtProperty(QColor)
    def backgroundColor(self):
        return self._background_color

    @backgroundColor.setter
    def backgroundColor(self, color):
        self._background_color = color
        self.renderer.SetBackground(color.getRgbF()[:3])
        self.update_render()

    @pyqtProperty(QColor)
    def backgroundColor2(self):
        return self._background_color2

    @backgroundColor2.setter
    def backgroundColor2(self, color2):
        self._background_color2 = color2
        self.renderer.GradientBackgroundOn()
        self.renderer.SetBackground2(color2.getRgbF()[:3])
        self.update_render()

# this draws the program boundary outline
class PathBoundaries:
    show_program_bounds = bool()
    def __init__(self, camera, path_actor):
        self.path_actor = path_actor
        bounds = self.path_actor.GetBounds()
        xmin = bounds[0]
        xmax = bounds[1]
        ymin = bounds[2]
        ymax = bounds[3]
        zmin = bounds[4]
        zmax = bounds[5]

        cube_axes_actor = vtk.vtkCubeAxesActor()
        cube_axes_actor.SetBounds(bounds)
        cube_axes_actor.SetCamera(camera)
        cube_axes_actor.SetFlyModeToStaticEdges()
        cube_axes_actor.GetXAxesLinesProperty().SetColor(0.8, 0.0, 0.3)
        cube_axes_actor.GetYAxesLinesProperty().SetColor(0.8, 0.0, 0.3)
        cube_axes_actor.GetZAxesLinesProperty().SetColor(0.8, 0.0, 0.3)

        if PathBoundaries.show_program_bounds is True:
            cube_axes_actor.XAxisVisibilityOn()
            cube_axes_actor.YAxisVisibilityOn()
            cube_axes_actor.ZAxisVisibilityOn()
        else:
            cube_axes_actor.XAxisVisibilityOff()
            cube_axes_actor.YAxisVisibilityOff()
            cube_axes_actor.ZAxisVisibilityOff()

        cube_axes_actor.XAxisTickVisibilityOff()
        cube_axes_actor.YAxisTickVisibilityOff()
        cube_axes_actor.ZAxisTickVisibilityOff()
        cube_axes_actor.XAxisLabelVisibilityOff()
        cube_axes_actor.YAxisLabelVisibilityOff()
        cube_axes_actor.ZAxisLabelVisibilityOff()
        self.actor = cube_axes_actor
        
    def get_actor(self):
        return self.actor

class PathCache:
    def __init__(self, current_position):
        self.current_position = current_position
        self.index = 0
        self.num_points = 2
        self.points = vtk.vtkPoints()
        self.points.InsertNextPoint(current_position)
        self.lines = vtk.vtkCellArray()
        self.lines.InsertNextCell(1)  # number of points
        self.lines.InsertCellPoint(0)
        self.lines_polygon_data = vtk.vtkPolyData()
        self.polygon_mapper = vtk.vtkPolyDataMapper()
        self.actor = vtk.vtkActor()
        self.actor.GetProperty().SetColor(yellow)
        self.actor.GetProperty().SetLineWidth(2)
        self.actor.GetProperty().SetOpacity(0.5)
        self.actor.SetMapper(self.polygon_mapper)
        self.lines_polygon_data.SetPoints(self.points)
        self.lines_polygon_data.SetLines(self.lines)
        self.polygon_mapper.SetInputData(self.lines_polygon_data)
        self.polygon_mapper.Update()

    def add_line_point(self, point):
        self.index += 1
        self.points.InsertNextPoint(point)
        self.points.Modified()
        self.lines.InsertNextCell(self.num_points)
        self.lines.InsertCellPoint(self.index - 1)
        self.lines.InsertCellPoint(self.index)
        self.lines.Modified()

    def get_actor(self):
        return self.actor


# this draws the machine boundary outline
class Machine:
    def __init__(self, axis):
        cube_axes_actor = vtk.vtkCubeAxesActor()
        xmax = axis[0]["max_position_limit"]
        xmin = axis[0]["min_position_limit"]
        ymax = axis[1]["max_position_limit"]
        ymin = axis[1]["min_position_limit"]
        zmax = axis[2]["max_position_limit"]
        zmin = axis[2]["min_position_limit"]
        cube_axes_actor.SetBounds(xmin, xmax, ymin, ymax, zmin, zmax)
        cube_axes_actor.SetFlyModeToStaticEdges()
        cube_axes_actor.GetXAxesLinesProperty().SetColor(0.8, 0.0, 0.3)
        cube_axes_actor.GetYAxesLinesProperty().SetColor(0.8, 0.0, 0.3)
        cube_axes_actor.GetZAxesLinesProperty().SetColor(0.8, 0.0, 0.3)
        cube_axes_actor.XAxisTickVisibilityOff()
        cube_axes_actor.YAxisTickVisibilityOff()
        cube_axes_actor.ZAxisTickVisibilityOff()
        cube_axes_actor.XAxisLabelVisibilityOff()
        cube_axes_actor.YAxisLabelVisibilityOff()
        cube_axes_actor.ZAxisLabelVisibilityOff()
        cube_axes_actor.GetProperty().SetLineStipplePattern(0xf0f0)
        cube_axes_actor.GetProperty().SetLineStippleRepeatFactor(1)
        self.cube_actor = cube_axes_actor

    def get_actor(self):
        return self.cube_actor


class Axes:
    def __init__(self):

        self.lathe = LATHE
        self.units = MACHINE_UNITS
        self.axis_mask = STATUS.stat.axis_mask
        if self.units in ("mm", "metric"):
            self.length = 25.0
        else:
            self.length = 1.0

        transform = vtk.vtkTransform()
        transform.Translate(0.0, 0.0, 0.0)  # Z up
        self.actor = vtk.vtkAxesActor()
        self.actor.SetUserTransform(transform)
        self.actor.AxisLabelsOff()
        self.actor.SetShaftTypeToLine()
        self.actor.SetTipTypeToCone()

        # Lathe modes
        if self.axis_mask == 3:
            self.actor.SetTotalLength(self.length, self.length, 0)
        elif self.axis_mask == 5:
            self.actor.SetTotalLength(self.length, 0, self.length)
        elif self.axis_mask == 6:
            self.actor.SetTotalLength(0, self.length, self.length)
        # Mill mode
        else:
            self.actor.SetTotalLength(self.length, self.length, self.length)

    def get_actor(self):
        return self.actor


class Tool:
    def __init__(self, tool):
        self.units = MACHINE_UNITS
        self.lathe = LATHE
        if self.units in ("mm", "metric"):
            self.height = 25.4 * 2.0
        else:
            self.height = 2.0

        if self.lathe is True:
            if tool['id'] == 0 or tool['id'] == -1:
                polygonSource = vtk.vtkRegularPolygonSource()
                polygonSource.SetNumberOfSides(64)
                polygonSource.SetRadius(0.035)
                polygonSource.SetCenter(0.0, 0.0, 0.0)
                transform = vtk.vtkTransform()
                transform.RotateWXYZ(90, 1, 0, 0)
                transform_filter = vtk.vtkTransformPolyDataFilter()
                transform_filter.SetTransform(transform)
                transform_filter.SetInputConnection(polygonSource.GetOutputPort())
                transform_filter.Update()
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(transform_filter.GetOutputPort())
            else:
                if tool['orientation'] == 1 and tool['frontangle'] == 90 and tool['backangle'] == 90:
                    # Setup four points
                    points = vtk.vtkPoints()
                    points.InsertNextPoint((-tool['xoffset'], 0.0, -tool['zoffset']))
                    points.InsertNextPoint((-tool['xoffset'] + 0.5, 0.0, -tool['zoffset']))
                    points.InsertNextPoint((-tool['xoffset'] + 0.5, 0.0, -tool['zoffset'] - 0.05))
                    points.InsertNextPoint((-tool['xoffset'], 0.0, -tool['zoffset'] - 0.05))
                    # Create the polygon
                    # Create a quad on the four points
                    quad = vtk.vtkQuad()
                    quad.GetPointIds().SetId(0, 0)
                    quad.GetPointIds().SetId(1, 1)
                    quad.GetPointIds().SetId(2, 2)
                    quad.GetPointIds().SetId(3, 3)
                    # Add the polygon to a list of polygons
                    polygons = vtk.vtkCellArray()
                    polygons.InsertNextCell(quad)
                    # Create a PolyData
                    polygonPolyData = vtk.vtkPolyData()
                    polygonPolyData.SetPoints(points)
                    polygonPolyData.SetPolys(polygons)
                    # Create a mapper and actor
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(polygonPolyData)
                elif tool['orientation'] == 2 and tool['frontangle'] == 90 and tool['backangle'] == 90:
                    # Setup four points
                    points = vtk.vtkPoints()
                    points.InsertNextPoint((-tool['xoffset'], 0.0, -tool['zoffset']))
                    points.InsertNextPoint((-tool['xoffset'], 0.0, -tool['zoffset'] + 0.05))
                    points.InsertNextPoint((-tool['xoffset'] + 0.5, 0.0, -tool['zoffset'] + 0.05))
                    points.InsertNextPoint((-tool['xoffset'] + 0.5, 0.0, -tool['zoffset']))
                    # Create the polygon
                    # Create a quad on the four points
                    quad = vtk.vtkQuad()
                    quad.GetPointIds().SetId(0, 0)
                    quad.GetPointIds().SetId(1, 1)
                    quad.GetPointIds().SetId(2, 2)
                    quad.GetPointIds().SetId(3, 3)
                    # Add the polygon to a list of polygons
                    polygons = vtk.vtkCellArray()
                    polygons.InsertNextCell(quad)
                    # Create a PolyData
                    polygonPolyData = vtk.vtkPolyData()
                    polygonPolyData.SetPoints(points)
                    polygonPolyData.SetPolys(polygons)
                    # Create a mapper and actor
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(polygonPolyData)
                elif tool['orientation'] == 3 and tool['frontangle'] == 90 and tool['backangle'] == 90:
                    # Setup four points
                    points = vtk.vtkPoints()
                    points.InsertNextPoint((-tool['xoffset'], 0.0, -tool['zoffset']))
                    points.InsertNextPoint((-tool['xoffset'], 0.0, -tool['zoffset'] + 0.05 ))
                    points.InsertNextPoint((-tool['xoffset'] - 0.5, 0.0, -tool['zoffset'] + 0.05))
                    points.InsertNextPoint((-tool['xoffset'] - 0.5, 0.0, -tool['zoffset']))
                    # Create the polygon
                    # Create a quad on the four points
                    quad = vtk.vtkQuad()
                    quad.GetPointIds().SetId(0, 0)
                    quad.GetPointIds().SetId(1, 1)
                    quad.GetPointIds().SetId(2, 2)
                    quad.GetPointIds().SetId(3, 3)
                    # Add the polygon to a list of polygons
                    polygons = vtk.vtkCellArray()
                    polygons.InsertNextCell(quad)
                    # Create a PolyData
                    polygonPolyData = vtk.vtkPolyData()
                    polygonPolyData.SetPoints(points)
                    polygonPolyData.SetPolys(polygons)
                    # Create a mapper and actor
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(polygonPolyData)
                elif tool['orientation'] == 4 and tool['frontangle'] == 90 and tool['backangle'] == 90:
                    # Setup four points
                    points = vtk.vtkPoints()
                    points.InsertNextPoint((-tool['xoffset'], 0.0, -tool['zoffset']))
                    points.InsertNextPoint((-tool['xoffset'], 0.0, -tool['zoffset'] - 0.05))
                    points.InsertNextPoint((-tool['xoffset'] - 0.5, 0.0, -tool['zoffset'] - 0.05))
                    points.InsertNextPoint((-tool['xoffset'] - 0.5, 0.0, -tool['zoffset']))
                    # Create the polygon
                    # Create a quad on the four points
                    quad = vtk.vtkQuad()
                    quad.GetPointIds().SetId(0, 0)
                    quad.GetPointIds().SetId(1, 1)
                    quad.GetPointIds().SetId(2, 2)
                    quad.GetPointIds().SetId(3, 3)
                    # Add the polygon to a list of polygons
                    polygons = vtk.vtkCellArray()
                    polygons.InsertNextCell(quad)
                    # Create a PolyData
                    polygonPolyData = vtk.vtkPolyData()
                    polygonPolyData.SetPoints(points)
                    polygonPolyData.SetPolys(polygons)
                    # Create a mapper and actor
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(polygonPolyData)
                elif tool['orientation'] == 9:
                    radius = tool['diameter'] / 2
                    # Setup four points
                    points = vtk.vtkPoints()
                    points.InsertNextPoint((-tool['xoffset'] + radius, 0.0, -tool['zoffset']))
                    points.InsertNextPoint((-tool['xoffset'] + radius, 0.0, -tool['zoffset'] + 1.0))
                    points.InsertNextPoint((-tool['xoffset'] - radius, 0.0, -tool['zoffset'] + 1.0))
                    points.InsertNextPoint((-tool['xoffset'] - radius, 0.0, -tool['zoffset']))
                    # Create the polygon
                    # Create a quad on the four points
                    quad = vtk.vtkQuad()
                    quad.GetPointIds().SetId(0, 0)
                    quad.GetPointIds().SetId(1, 1)
                    quad.GetPointIds().SetId(2, 2)
                    quad.GetPointIds().SetId(3, 3)
                    # Add the polygon to a list of polygons
                    polygons = vtk.vtkCellArray()
                    polygons.InsertNextCell(quad)
                    # Create a PolyData
                    polygonPolyData = vtk.vtkPolyData()
                    polygonPolyData.SetPoints(points)
                    polygonPolyData.SetPolys(polygons)
                    # Create a mapper and actor
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(polygonPolyData)
                else:
                    positive = 1
                    negative = -1
                    if tool['orientation'] == 1:
                        fa_x_pol = negative
                        fa_z_pol = negative
                        ba_x_pol = negative
                        ba_z_pol = negative
                    elif tool['orientation'] == 2:
                        fa_x_pol = negative
                        fa_z_pol = positive
                        ba_x_pol = negative
                        ba_z_pol = positive
                    elif tool['orientation'] == 3:
                        fa_x_pol = positive
                        fa_z_pol = positive
                        ba_x_pol = positive
                        ba_z_pol = positive
                    elif tool['orientation'] == 4:
                        fa_x_pol = positive
                        fa_z_pol = negative
                        ba_x_pol = positive
                        ba_z_pol = negative
                    elif tool['orientation'] == 5:
                        fa_x_pol = positive
                        fa_z_pol = negative
                        ba_x_pol = negative
                        ba_z_pol = positive
                    elif tool['orientation'] == 6:
                        fa_x_pol = negative
                        fa_z_pol = positive
                        ba_x_pol = negative
                        ba_z_pol = negative
                    elif tool['orientation'] == 7:
                        fa_x_pol = positive
                        fa_z_pol = positive
                        ba_x_pol = negative
                        ba_z_pol = positive
                    elif tool['orientation'] == 8:
                        fa_x_pol = positive
                        fa_z_pol = positive
                        ba_x_pol = positive
                        ba_z_pol = negative
                    else:
                        fa_x_pol = 0.0
                        fa_z_pol = 0.0
                        ba_x_pol = 0.0
                        ba_z_pol = 0.0
                    A = radians(float(tool['frontangle']))
                    B = radians(float(tool['backangle']))
                    C = 0.35
                    p1_x = abs(C * sin(A))
                    p1_z = abs(C * cos(A))
                    p2_x = abs(C * sin(B))
                    p2_z = abs(C * cos(B))
                    p1_x_pos = p1_x * fa_x_pol
                    p1_z_pos = p1_z * fa_z_pol
                    p2_x_pos = p2_x * ba_x_pol
                    p2_z_pos = p2_z * ba_z_pol
                    # Setup three points
                    points = vtk.vtkPoints()
                    points.InsertNextPoint((tool['xoffset'], 0.0, -tool['zoffset']))
                    points.InsertNextPoint((tool['xoffset'] + p1_x_pos, 0.0, p1_z_pos - tool['zoffset']))
                    points.InsertNextPoint((tool['xoffset'] + p2_x_pos, 0.0, p2_z_pos - tool['zoffset']))
                    # Create the polygon
                    polygon = vtk.vtkPolygon()
                    polygon.GetPointIds().SetNumberOfIds(3)  # make a quad
                    polygon.GetPointIds().SetId(0, 0)
                    polygon.GetPointIds().SetId(1, 1)
                    polygon.GetPointIds().SetId(2, 2)
                    # Add the polygon to a list of polygons
                    polygons = vtk.vtkCellArray()
                    polygons.InsertNextCell(polygon)
                    # Create a PolyData
                    polygon_poly_data = vtk.vtkPolyData()
                    polygon_poly_data.SetPoints(points)
                    polygon_poly_data.SetPolys(polygons)
                    transform = vtk.vtkTransform()
                    transform.RotateWXYZ(180, 0, 0, 1)
                    transform_filter = vtk.vtkTransformPolyDataFilter()
                    transform_filter.SetTransform(transform)
                    transform_filter.SetInputData(polygon_poly_data)
                    transform_filter.Update()
                    # Create a mapper
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputConnection(transform_filter.GetOutputPort())

        else:
            if tool['id'] == 0 or tool['diameter'] < .05:
                transform = vtk.vtkTransform()
                source = vtk.vtkConeSource()
                source.SetHeight(self.height / 2)
                source.SetCenter(-self.height / 4 - tool['zoffset'], -tool['yoffset'], -tool['xoffset'])
                source.SetRadius(self.height / 4)
                source.SetResolution(64)
                transform.RotateWXYZ(90, 0, 1, 0)
                transform_filter = vtk.vtkTransformPolyDataFilter()
                transform_filter.SetTransform(transform)
                transform_filter.SetInputConnection(source.GetOutputPort())
                transform_filter.Update()
                # Create a mapper
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(transform_filter.GetOutputPort())
            else:
                transform = vtk.vtkTransform()
                source = vtk.vtkCylinderSource()
                source.SetHeight(self.height / 2)
                source.SetCenter(-tool['xoffset'], self.height / 4 - tool['zoffset'], tool['yoffset'])
                source.SetRadius(tool['diameter'] / 2)
                source.SetResolution(64)
                transform.RotateWXYZ(90, 1, 0, 0)
                transform_filter = vtk.vtkTransformPolyDataFilter()
                transform_filter.SetTransform(transform)
                transform_filter.SetInputConnection(source.GetOutputPort())
                transform_filter.Update()
                # Create a mapper
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(transform_filter.GetOutputPort())
        # Create an actor
        self.actor = vtk.vtkActor()
        self.actor.SetMapper(mapper)

    def get_actor(self):
        return self.actor


class CoordinateWidget:
    def __init__(self, interactor):
        colors = vtk.vtkNamedColors()
        axes = vtk.vtkAxesActor()
        widget = vtk.vtkOrientationMarkerWidget()
        rgba = [0] * 4
        colors.GetColor("Carrot", rgba)
        widget.SetOutlineColor(rgba[0], rgba[1], rgba[2])
        widget.SetOrientationMarker(axes)
        widget.SetInteractor(interactor)
        widget.SetViewport(0.0, 0.0, 0.4, 0.4)
        widget.SetEnabled(1)
        widget.InteractiveOn()
