import numpy as np
from pymodaq_utils.utils import ThreadCommand
from pymodaq_data.data import DataToExport
from pymodaq_gui.parameter import Parameter
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.data import DataFromPlugins
from pymodaq_plugins_inficon.hardware.STM2_Python_Wrapper import InficonSTM2

class DAQ_0DViewer_Inficon_STM2(DAQ_Viewer_base):
    """ Module class for Inficon STM-2 instrument.
        It needs the Inficon driver in order to communicate with PyMoDAQ.
        It has been tested only with Inficon STM-2 rate/thickness monitor.
    =======================================================================
    Attributes:
    -----------
    controller: object
        InficonSTM2 object from python wrapper STM2_Serial_Communication that uses SerialBaseSMDP methods to communicate
        with the instrument according to the specific protocol (Sycon Multi Drop Protocol) described in its documentation.
         
    ========================================================================

    """

    params = comon_parameters+[
        {'title': 'Device serial number :', 'name': 'device_serial_number', 'type': 'list'},
        {'title': 'Device information :', 'name': 'device_info', 'type': 'str', 'value': '', 'readonly': True},
        {'title': 'Crystal status :', 'name': 'crystal_status', 'type': 'str', 'value': '', 'readonly': True},
        {'title': 'Crystal life (%) :', 'name': 'crystal_life', 'type': 'str', 'value': '', 'readonly': True},
        {'title': 'Timer (H:MM:SS) :', 'name': 'timer', 'type': 'str', 'value': '', 'readonly': True},
        {'title': 'Set default parameters :', 'name': 'set_default_parameters', 'type': 'bool'},
        {'title': 'Zeroes thickness :', 'name': 'set_thickness_zeroes', 'type': 'bool'},
        {'title': 'Zeroes timer :', 'name': 'set_timer_zeroes', 'type': 'bool'},
        {'title': 'Film name :', 'name': 'film_name', 'type': 'str'},
        {'title': 'Film density :', 'name': 'film_density', 'type': 'float', 'max': 99.99, 'min': 0.40},
        {'title': 'Film Z-ratio :', 'name': 'film_zratio', 'type': 'float', 'max': 9.999, 'min': 0.100},
        {'title': 'Film tooling (%) :', 'name': 'film_tooling', 'type': 'float', 'max': 999.9, 'min': 10.0},
        {'title': 'Samples number :', 'name': 'samples_number', 'type': 'int', 'max': 50, 'min': 1}
        ]

    def link_ports_and_sn(self):
        list_serial_numbers = []
        if self.stm2_ports:
            for port in self.stm2_ports:
                serial_number = InficonSTM2(port).get_serial_number()
                list_serial_numbers.append(serial_number + ' (' + port +')')
        self.settings.child('device_serial_number').setLimits(list_serial_numbers)

    def ini_attributes(self):
        self.controller: InficonSTM2 = None
        self.controller = None
        self.stm2_ports = InficonSTM2().stm2_ports
        self.port = None
        self.port_change = False
        self.link_ports_and_sn()
        self.emit_status(ThreadCommand('Update_Status', ['Detected STM-2 COM ports : ' + str(self.stm2_ports), 'log']))

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            Device serial number : list of detected STM-2 monitors, can be selected during initialization
            (changes may occur between units, see red light on it).
            Set default parameters : sets the unit to its constructor default values.
            Zeroes thickness : as in title.
            Zeroes timer : as in title.
            Film name : sets unit film name (8 characters max), nice to remember who is who.
            Film density : sets film density on the unit for calculated values.
            Film Z-ratio : sets film Z-ratio on the unit for calculated values.
            Film tooling : sets film tooling on the unit for calculated values.
            Samples number : sets sample number on the unit for calculated values.
        """
        try:
            if param.name() == 'device_serial_number':
                old_port = self.port
                self.port = param.value()[-5:-1]
                if old_port != self.port:
                    self.port_change = True
                    self.controller = InficonSTM2(self.port)
                else:
                    self.port_change = False
                self.emit_status(ThreadCommand('Update_Status', ["Selected port is now : " + str(self.port), 'log']))
            elif param.name() == 'set_default_parameters':
                self.controller.set_default_parameters()
            elif param.name() == 'set_thickness_zeroes':
                self.controller.set_thickness_zeroes()
            elif param.name() == 'set_timer_zeroes':
                self.controller.set_timer_zeroes()
            elif param.name() == 'film_name':
                self.controller.set_film_name(param.value())
            elif param.name() == 'film_density':
                self.controller.set_film_density(param.value())
            elif param.name() == 'film_zratio':
                self.controller.set_film_zratio(param.value())
            elif param.name() == 'film_tooling':
                self.controller.set_film_tooling(param.value())
            elif param.name() == 'samples_number':
                self.controller.set_samples_number(param.value())
            self.update_parameter_branch()
        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [str(e), 'log']))

    def update_parameter_branch(self):
        infos = ('Model and firmware version : {}, Build type : {}, Firmware CRC : {}, Reset Status : {}'.format
                (self.controller.get_infos(), self.controller.get_build_type(), self.controller.get_firmware_crc(),
                self.controller.get_reset_status()))
        self.settings.child('device_info').setValue(infos)
        self.settings.child('crystal_status').setValue(self.controller.get_cristal_status())
        self.settings.child('crystal_life').setValue(self.controller.get_cristal_life())
        self.settings.child('timer').setValue(self.controller.get_timer())
        self.settings.child('film_name').setValue(self.controller.get_film_name())
        self.settings.child('film_density').setValue(self.controller.get_film_density())
        self.settings.child('film_zratio').setValue(self.controller.get_film_zratio())
        self.settings.child('film_tooling').setValue(self.controller.get_film_tooling())
        self.settings.child('samples_number').setValue(self.controller.get_samples_number())

    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin (Slave case). None if only one actuator/detector by controller
            (Master case)

        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """
        self.ini_controller_init(slave_controller=controller)
        if (self.stm2_ports != []) & self.is_master:
            if not self.port_change:
                self.port = self.stm2_ports[0]
            self.controller = InficonSTM2(self.port)
        self.update_parameter_branch()
        self.dte_signal_temp.emit(DataToExport('STM-2 Data',
                                               data=[DataFromPlugins(name='STM-2 Frequency',
                                                                     data=[np.array([0, 5])],
                                                                     dim='Data0D',
                                                                     labels=['Frequency (Hz)']),
                                                     DataFromPlugins(name='STM-2 Thickness',
                                                                     data=[np.array([0, 5])],
                                                                     dim='Data0D',
                                                                     labels=['Thickness (Å)']),
                                                     DataFromPlugins(name='STM-2 Film mass',
                                                                     data=[np.array([0, 5])],
                                                                     dim='Data0D',
                                                                     labels=['Film mass (µg/cm²)']),
                                                     DataFromPlugins(name='STM-2 Rate',
                                                                     data=[np.array([0, 5])],
                                                                     dim='Data0D',
                                                                     labels=['Rate (Å/s)']),
                                                     DataFromPlugins(name='STM-2 Mass accumulation rate',
                                                                     data=[np.array([0, 5])],
                                                                     dim='Data0D',
                                                                     labels=['Mass accumulation rate (μg/(*s/cm²))'])]))
        info = "Default values for selected STM-2 should be printed and graphs should appear."
        initialized = bool(self.controller)
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        self.controller = None

    def grab_data(self, Naverage=1, **kwargs):
        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Number of hardware averaging (if hardware averaging is possible, self.hardware_averaging should be set to
            True in class preamble and you should code this implementation)
        kwargs: dict
            others optionals arguments
        """
        self.dte_signal.emit(DataToExport('STM-2 Data',
                                               data=[DataFromPlugins(name='STM-2 Frequency',
                                                                     data=[np.array([self.controller.get_frequency()])],
                                                                     dim='Data0D',
                                                                     labels=['Frequency (Hz)']),
                                                     DataFromPlugins(name='STM-2 Thickness',
                                                                     data=[np.array([self.controller.get_thickness()])],
                                                                     dim='Data0D',
                                                                     labels=['Thickness (Å)']),
                                                     DataFromPlugins(name='STM-2 Film mass',
                                                                     data=[np.array([self.controller.get_film_mass()])],
                                                                     dim='Data0D',
                                                                     labels=['Film mass (µg/cm²)']),
                                                     DataFromPlugins(name='STM-2 Rate',
                                                                     data=[np.array([self.controller.get_rate()])],
                                                                     dim='Data0D',
                                                                     labels=['Rate (Å/s)']),
                                                     DataFromPlugins(name='STM-2 Mass accumulation rate',
                                                                     data=[np.array([self.controller.get_mass_accumulation_rate()])],
                                                                     dim='Data0D',
                                                                     labels=['Mass accumulation rate (μg/(*s/cm²))'])]))

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        self.emit_status(ThreadCommand('Update_Status', ['Stopped']))
        ##############################
        return ''


if __name__ == '__main__':
    main(__file__)
