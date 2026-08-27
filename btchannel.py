from radiochannel import RadioChannel
from pydbus import SystemBus
import json

class BtChannel(RadioChannel):

    def __init__(self):
        self.force_metadata_refresh = False
        self.bus = SystemBus()
        #TODO : Dynamically set the following
        #TODO : Try catch this
        self.media_player = self.bus.get('org.bluez', '/org/bluez/hci0/dev_E0_33_8E_0F_23_53/player0')
        self.device = self.bus.get('org.bluez', '/org/bluez/hci0/dev_E0_33_8E_0F_23_53')

    def channel_type(self):
        return "BLUETOOTH"

    def get_channel_name(self) -> str:
        # TODO: Try catch this
        return self.device.Name

    def get_channel_url(self) -> str:
        return None

    def get_current_track_info(self) -> dict[str, str]:
        #TODO : try catch this
        trackinfo = self.media_player.Track
        infos = {
            "track_name": trackinfo['Title'],
            "artist_name": trackinfo['Artist']
        }
        return infos

    def get_display_text(self) -> str:
        infos = self.get_current_track_info()
        return " | ".join(infos.values())

    def fetch_metadata(self, force: bool = False):
        # TODO : Use DBus to get track info
        pass

    def get_debug(self) -> str:
        return "Empty"