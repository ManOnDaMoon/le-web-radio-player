from radiochannel import RadioChannel

class BtChannel(RadioChannel):

    def __init__(self):
        self.force_metadata_refresh = False

    def channel_type(self):
        return "BLUETOOTH"

    def get_channel_name(self) -> str:
        # TODO: Get Bluetooth paired device name
        return "Bluetooth"

    def get_channel_url(self) -> str:
        return None

    def get_current_track_info(self) -> dict[str, str]:
        infos = {
            "track_name": "Track",
            "artist_name": "Artist"
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