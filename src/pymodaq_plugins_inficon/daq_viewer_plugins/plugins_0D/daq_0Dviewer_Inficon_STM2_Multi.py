import numpy as np

from pymodaq_utils.utils import ThreadCommand
from pymodaq_data.data import DataToExport
from pymodaq_gui.parameter import Parameter
from pymodaq_gui.parameter.pymodaq_ptypes import GroupParameter, registerParameterType

from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.data import DataFromPlugins

from pymodaq_plugins_inficon.hardware.STM2_Python_Wrapper import InficonSTM2


qcm_params = [
    {'title': 'Device serial number :', 'name': 'device_serial_number', 'type': 'list'},
    {'title': 'Crystal status :', 'name': 'crystal_status', 'type': 'str', 'value': '', 'readonly': True},
]


class STM2ScalableGroup(GroupParameter):
    """Group parameter allowing the user to add/remove QCM_XX entries at runtime, each holding
    its own copy of qcm_params (device_serial_number, crystal_status)."""

    def __init__(self, **opts):
        opts['type'] = 'group'
        opts['addText'] = 'Add QCM'
        super().__init__(**opts)

    def addNew(self):
        indexes = [int(child.name().split('_')[1]) for child in self.children()
                   if child.name().startswith('qcm_')]
        new_index = max(indexes) + 1 if indexes else max(len(self.children()), 1)
        children = [{**p} for p in qcm_params]  # fresh copy, don't share dicts between QCMs
        self.addChild({
            'title': f'QCM {new_index}',
            'name': f'qcm_{new_index}',
            'type': 'bool',
            'value': True,
            'removable': True,
            'renamable': False,
            'children': children,
        })


registerParameterType('groupstm2', STM2ScalableGroup, override=True)


class DAQ_0DViewer_Inficon_STM2_Multi(DAQ_Viewer_base):
    """ Instrument plugin class for a OD viewer managing a variable number of Inficon STM-2 units.

    Units are added/removed at runtime from the 'activated_stm2' group parameter (à la Mock
    plugin). Film settings (name/density/zratio/samples) and the zero-thickness command are
    broadcast to every currently connected unit; each unit keeps its own serial number selection
    and crystal status readout. Each checked channel (frequency/thickness/thickness_rate) opens
    its own window, plotting every connected unit as a separate curve within it.

    Attributes
    -----------
    controllers: dict[str, InficonSTM2]
        Maps a QCM group child name ('qcm_1', 'qcm_2', ...) to its open InficonSTM2 connection.
    """

    params = comon_parameters + [
        {'title': 'Selected channel :', 'name': 'channel', 'type': 'group', 'children': [
            {'title': 'Frequency (Hz)', 'name': 'frequency', 'type': 'bool', 'value': True},
            {'title': 'Thickness (Å)', 'name': 'thickness', 'type': 'bool', 'value': True},
            {'title': 'Thickness growth rate (Å/s)', 'name': 'thickness_rate', 'type': 'bool', 'value': True},
        ]},
        {'title': 'Actualiser les ports :', 'name': 'refresh_ports', 'type': 'bool_push'},
        {'title': 'Zeroes thickness :', 'name': 'set_timer_thickness_zeroes', 'type': 'bool_push'},
        {'title': 'Film name :', 'name': 'film_name', 'type': 'str'},
        {'title': 'Film density :', 'name': 'film_density', 'type': 'float', 'max': 99.99, 'min': 0.40},
        {'title': 'Film Z-ratio :', 'name': 'film_zratio', 'type': 'float', 'max': 9.999, 'min': 0.100},
        {'title': 'Samples number :', 'name': 'samples_number', 'type': 'int', 'max': 50, 'min': 1, 'value': 5},
        {'title': 'Activated STM-2', 'name': 'activated_stm2', 'type': 'groupstm2', 'children': [
            {'title': 'QCM 1', 'name': 'qcm_1', 'type': 'bool', 'value': True,
             'removable': True, 'renamable': False,
             'children': [{**p} for p in qcm_params]},
            {'title': 'QCM 2', 'name': 'qcm_2', 'type': 'bool', 'value': True,
             'removable': True, 'renamable': False,
             'children': [{**p} for p in qcm_params]},
        ]},
    ]

    _channel_getters = {
        'frequency': ('get_frequency', 'Hz'),
        'thickness': ('get_thickness', 'Å'),
        'thickness_rate': ('get_rate', 'Å/s'),
    }

    def _active_channels(self):
        """Names of the currently checked channel booleans, in tree order."""
        return [ch.name() for ch in self.settings.child('channel').children() if ch.value()]

    @staticmethod
    def _port_from_label(label: str) -> str:
        return label.rsplit('(', 1)[-1].rstrip(')') if label else ''

    def ini_attributes(self):
        self.controllers: dict = {}      # nom du QCM -> InficonSTM2 connecté
        self._ports_in_use: dict = {}    # nom du QCM -> port actuellement connecté
        self.stm2_ports = InficonSTM2().stm2_ports
        self.refresh_available_ports()

    def refresh_available_ports(self):
        """Scan the COM ports and update every QCM's device_serial_number choices, keeping the
        currently selected value if it is still valid."""
        self.stm2_ports = InficonSTM2().stm2_ports
        labels = []
        for port in self.stm2_ports:
            try:
                sn = InficonSTM2(port).get_serial_number()
                labels.append(f'{sn} ({port})')
            except Exception as e:
                self.emit_status(ThreadCommand('Update_Status', [f"Port {port} injoignable : {e}", 'log']))

        for qcm in self.settings.child('activated_stm2').children():
            sn_child = qcm.child('device_serial_number')
            current = sn_child.value()
            sn_child.setLimits(labels)
            if current in labels:
                sn_child.setValue(current)

        self.emit_status(ThreadCommand('Update_Status', [f'STM-2 détectés : {labels}', 'log']))

    def sync_controllers(self):
        """Rebuild self.controllers from the current parameter tree: connect any activated QCM
        with a chosen serial number that isn't connected yet (or whose port changed), and
        disconnect any QCM that got deactivated, removed, or emptied of its port choice."""
        active = {}
        for qcm in self.settings.child('activated_stm2').children():
            name = qcm.name()
            if not qcm.value():  # case décochée
                continue
            label = qcm.child('device_serial_number').value()
            port = self._port_from_label(label)
            if not port:
                continue
            active[name] = port

        # déconnecter ce qui n'est plus actif
        for name in list(self.controllers.keys()):
            if name not in active:
                self.controllers.pop(name, None)
                self._ports_in_use.pop(name, None)

        # connecter/reconnecter ce qui a changé
        for name, port in active.items():
            if self._ports_in_use.get(name) != port:
                try:
                    ctrl = InficonSTM2(port)
                    ctrl.set_timer_thickness_zeroes()
                    self.controllers[name] = ctrl
                    self._ports_in_use[name] = port
                    self.settings.child('activated_stm2', name, 'crystal_status').setValue(
                        ctrl.get_cristal_status())
                except Exception as e:
                    self.emit_status(ThreadCommand('Update_Status', [f'Connexion {name} impossible : {e}', 'log']))

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings.

        Almost every change (activation toggle, serial number choice, QCM added/removed) is
        handled uniformly by resynchronising self.controllers with the parameter tree via
        sync_controllers(), exactly like set_Mock_data() rebuilds the Mock plugin's data from its
        tree on every commit. Only the genuinely "broadcast" commands (film settings, zeroing,
        port refresh) need an explicit branch.

        Parameters
        ----------
        param: Parameter
            channel : cases à cocher (frequency/thickness/thickness_rate) déterminant quels
                canaux/quelles fenêtres sont tracés au prochain grab, pas d'action ici.
            refresh_ports : relance la détection des ports/numéros de série disponibles.
            set_timer_thickness_zeroes : remet l'épaisseur à zéro sur tous les STM-2 connectés.
            film_name / film_density / film_zratio / samples_number : diffusés à tous les STM-2
                connectés.
            device_serial_number (sous 'activated_stm2') ou activation d'un QCM : gérés par
                sync_controllers().
        """
        try:
            if param.name() == 'refresh_ports':
                self.refresh_available_ports()

            self.sync_controllers()

            if param.name() == 'set_timer_thickness_zeroes':
                for ctrl in self.controllers.values():
                    ctrl.set_timer_thickness_zeroes()
            elif param.name() == 'film_name':
                for ctrl in self.controllers.values():
                    ctrl.set_film_name(param.value())
            elif param.name() == 'film_density':
                for ctrl in self.controllers.values():
                    ctrl.set_film_density(param.value())
            elif param.name() == 'film_zratio':
                for ctrl in self.controllers.values():
                    ctrl.set_film_zratio(param.value())
            elif param.name() == 'samples_number':
                for ctrl in self.controllers.values():
                    ctrl.set_samples_number(param.value())
        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [str(e), 'log']))

    def ini_detector(self, controller=None):
        """Detector communication initialization: connects every currently activated QCM."""
        self.refresh_available_ports()
        self.sync_controllers()

        channels = self._active_channels()
        controller_names = list(self.controllers.keys())
        dummy_dfp = [
            DataFromPlugins(name=channel,
                             data=[np.array([0]) for _ in controller_names],
                             dim='Data0D', labels=controller_names)
            for channel in channels
        ]
        self.dte_signal_temp.emit(DataToExport('STM-2 Group Data', data=dummy_dfp))

        initialized = len(self.controllers) > 0
        info = f"{len(self.controllers)} STM-2 connecté(s) : {', '.join(self.controllers.keys())}"
        return info, initialized

    def close(self):
        """Terminate the communication protocol with every connected STM-2."""
        self.controllers.clear()
        self._ports_in_use.clear()

    def grab_data(self, Naverage=1, **kwargs):
        """Grab every checked channel from every connected, activated STM-2.

        One DataFromPlugins is built per checked channel (frequency/thickness/thickness_rate),
        each containing one value per connected controller — so PyMoDAQ opens/updates one window
        per channel, each showing every QCM as a separate curve.
        """
        channels = self._active_channels()
        controller_names = list(self.controllers.keys())

        if not channels or not controller_names:
            return

        data_list = []
        for channel in channels:
            getter_name, unit = self._channel_getters[channel]
            values = []
            for name in controller_names:
                try:
                    value = getattr(self.controllers[name], getter_name)()
                except Exception as e:
                    self.emit_status(ThreadCommand('Update_Status', [f'Erreur lecture {name} : {e}', 'log']))
                    value = np.nan
                values.append(np.array([value]))
            data_list.append(DataFromPlugins(name=channel, data=values, dim='Data0D',
                                              labels=[f'{name} ({unit})' for name in controller_names]))

        self.dte_signal.emit(DataToExport('STM-2 Group Data', data=data_list))

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        self.emit_status(ThreadCommand('Update_Status', ['Stopped']))
        return ''


if __name__ == '__main__':
    main(__file__)