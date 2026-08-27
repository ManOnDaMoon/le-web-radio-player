from radiochannel import RadioChannel
from btchannel import BtChannel
import radiofrancechannels

import subprocess
import vlc

class Radio:
    __default_volume: int = 50
    __min_volume: int = 11 # 10% volume sounds like mute!
    __max_volume: int = 100
    __volume_step: int = 5

    __vlc_instance: vlc.Instance = vlc.Instance("--aout=alsa","--no-video","--intf","dummy")
    # "--aout=alsa" parameter to suppress PulseAudio error: "PulseAudio server connection failure: Connection refused"
    #TODO : Add "-q" to stop logging warnings?

    def __init__(self, debug: bool = False):
        if not debug: self.__vlc_instance.log_unset() # disable VLC console output
        self.power = False
        self.volume = self.__default_volume
        self.channels : list[RadioChannel] = radiofrancechannels.get_radiofrance_channels()
        self.channels.append(BtChannel())
        self.channel_num = 0
        self.media_player = self.__vlc_instance.media_player_new()
        if debug:
            self.media_player.event_manager().event_attach(
                vlc.EventType.MediaPlayerEncounteredError,
                self.callback_from_player, "media_player")
        self.current_channel = None
        self.display_text = None
        self.media = None
        self.set_display("OFF")

    def callback_from_player(self, event: vlc.Event, *args):
        self.set_display(f"callback called: {event.type}, from {args[0]}")

    # Returns the outcoming state of Power
    def toggle_on_off(self):
        if not self.power:
            self.power = True
            self.current_channel = self.channels[self.channel_num]
            if self.current_channel.channel_type() == "STREAM":
                self.media = self.__vlc_instance.media_new(self.current_channel.get_channel_url())
                self.media.get_mrl()
                self.media_player.audio_set_volume(self.volume)
                self.media_player.set_media(self.media)
                self.play()
            elif self.current_channel.channel_type() == "BLUETOOTH":
                subprocess.Popen(["systemctl", "start", "bluealsa-aplay"])
            self.current_channel.force_metadata_refresh = True
        else:
            self.power = False
            if self.current_channel.channel_type() == "STREAM":
                self.stop()
            elif self.current_channel.channel_type() == "BLUETOOTH":
                subprocess.Popen(["systemctl", "stop", "bluealsa-aplay"])
        return self.power

    def play(self):
        self.media_player.play()

    def switch_channel(self, num: int) -> str:
        num =  (self.channel_num + num) % len(self.channels)
        if self.power:

            # Properly close current channel
            if self.current_channel.channel_type() == "STREAM":
                self.stop()
            elif self.current_channel.channel_type() == "BLUETOOTH":
                subprocess.Popen(["systemctl", "stop", "bluealsa-aplay"])

            # Switch to next one and start properly
            self.channel_num = num
            self.current_channel = self.channels[self.channel_num]
            if self.current_channel.channel_type() == "STREAM":
                self.media = self.__vlc_instance.media_new(self.current_channel.get_channel_url())
                self.media.get_mrl()
                self.media_player.set_media(self.media)
                self.play()
            elif self.current_channel.channel_type() == "BLUETOOTH":
                subprocess.Popen(["systemctl", "start", "bluealsa-aplay"])
            self.current_channel.force_metadata_refresh = True
            return self.current_channel.get_channel_name()

        else:
            return ""

    def next_channel(self) -> str:
        return self.switch_channel(+1)

    def previous_channel(self) -> str :
        return self.switch_channel(-1)

    def set_volume(self, volume: int) -> int:
        #TODO: Handle bluetooth mode
        if self.media_player.get_state() == vlc.State.Playing:
            if volume >= self.__max_volume:
                self.volume = self.__max_volume
            else:
                if volume <= self.__min_volume:
                    self.volume = self.__min_volume
                else:
                    self.volume = volume
            self.media_player.audio_set_volume(self.volume)
            return self.volume
        else:
            return -1

    def volume_up(self) -> int:
        if self.media_player.get_state() == vlc.State.Playing:
            if self.volume <= self.__max_volume - self.__volume_step:
                self.volume = self.volume + self.__volume_step
                self.media_player.audio_set_volume(self.volume)
            return self.volume
        else:
            return -1

    def volume_down(self) -> int:
        if self.media_player.get_state() == vlc.State.Playing:
            if self.volume >= (self.__min_volume + self.__volume_step):
                self.volume = self.volume - self.__volume_step
                self.media_player.audio_set_volume(self.volume)
            return self.volume
        else:
            return -1

    def mute(self) -> int:
        if self.media_player.get_state() == vlc.State.Playing:
            if self.media_player.audio_get_volume() == 0:
                self.media_player.audio_set_volume(self.volume)
                return self.volume
            else:
                self.media_player.audio_set_volume(0)
                return 0
        else:
            return -1

    def stop(self):
        self.media_player.stop()
        self.current_channel = None

    def set_display(self, text):
        self.display_text = text

    def get_display(self) -> str:
        if not self.power:
            return ""
        if self.media_player.get_state() == vlc.State.Ended or self.media_player.get_state() == vlc.State.Error:
            return f"/!\\ Erreur de lecture - {self.display_text}"
        else:
            return self.current_channel.get_display_text()

    def get_channel_name(self) -> str:
        if self.current_channel:
            return self.current_channel.get_channel_name()
        return ""

    def fetch_metadata(self):
        if self.power:
            self.current_channel.fetch_metadata()

    def get_debug(self):
        if self.current_channel:
            return self.current_channel.get_debug()
        return ""