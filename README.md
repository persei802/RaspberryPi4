# RaspberryPi4
QtDragon implementation for RPi4 using VTK graphics.

- Install linuxcnc (available from http://buildbot.linuxcnc.org/dists/buster/master-rtpreempt/binary-armhf/)
- Install python-pyqt5
- Install vtk ( deb file provided)
- If you want to use qtdesigner, you will have to compile pyqt5 from source as the default installation is only for x86 architectures.

Apparently, VTK is capable of using the onboard GPU. To enable hardware acceleration, do the following:
1. Start raspi-config from a terminal
2. Go to Advanced Options > GL Driver
3. Select the option GL (Fake KMS) OpenGL desktop driver with fake KMS and Click OK
4. Go to Advanced Options > Memory Split
5. Type 128 (or 256) and click OK
6. Select Finish and Reboot the system.

Then check that the GPU is enabled with:
- cat /proc/device-tree/soc/firmwarekms@7e600000/status
- cat /proc/device-tree/v3dbus/v3d@7ec04000/status

If they both report okay, then hardware acceleration is working and activated.
