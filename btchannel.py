from radiochannel import RadioChannel
from pydbus import SystemBus

class BtChannel(RadioChannel):

    def __init__(self):
        self.force_metadata_refresh = False
        self.__systembus = SystemBus()
        self.__dbus = self.__systembus.get('.DBus')
        self.__media_player = None
        self.__media_transport = None
        self.__bluetooth_status = False
        self.__device_name = ''
        self.track_name = ''
        self.artist_name = ''

    # Returns True if Bluetooth is active and connected
    def update_bluetooth_status(self) -> bool:

        names = self.__dbus.ListNames()
        if not 'org.bluez' in names:
            # Bluetooth disabled
            self.__bluetooth_status = False
            self.__media_player = None
            self.__device_name = ''
            return False

        # Bluetooth enabled
        device_found = False
        self.__bluetooth_status = True
        bluez_bus = self.__systembus.get('org.bluez', '/')
        managed_objects = bluez_bus.GetManagedObjects()
        for obj_path, obj_data in managed_objects.items():
            if obj_data.get('org.bluez.Device1') is not None\
                    and obj_data.get('org.bluez.Device1').get('Connected'):
                device_found = True
                self.__device_name = obj_data.get('org.bluez.Device1').get('Name')
            if obj_data.get('org.bluez.MediaPlayer1') is not None:
                self.__media_player = self.__systembus.get('org.bluez', obj_path)
            if obj_data.get('org.bluez.MediaTransport1') is not None:
                self.__media_transport = self.__systembus.get('org.bluez', obj_path)
        if not device_found:
            self.__media_player = None
            self.__device_name = ''

        return device_found

    def get_channel_type(self):
        return "BLUETOOTH"

    def get_channel_name(self) -> str:
        return f"{self.__device_name if self.__device_name != '' else 'Bluetooth'}"

    def get_channel_url(self) -> str:
        return ''

    def get_current_track_info(self) -> dict[str, str]:
        infos = {
            "track_name": self.track_name,
            "artist_name": self.artist_name,
        }
        return infos

    def get_display_text(self) -> str:
        infos = self.get_current_track_info()
        return " | ".join(infos.values())

    def fetch_metadata(self, force: bool = False):
        if self.update_bluetooth_status():
            trackinfo = self.__media_player.Track
            self.track_name = trackinfo['Title']
            self.artist_name = trackinfo['Artist']
        else:
            self.track_name = 'Rechercher "radiodiane"'
            self.artist_name = 'Code : 0000 ou 1234'

    def set_volume(self, volume: int) -> int:
        if self.update_bluetooth_status():
            self.__media_transport.Volume = volume
            return self.__media_transport.Volume
        else:
            return -1

    def get_debug(self) -> str:
        return "Empty"