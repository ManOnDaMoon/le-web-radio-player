import radiofrancechannels

import vlc

class Radio:
    __default_volume: int = 50
    __min_volume: int = 11 # 10% volume sounds like mute!
    __max_volume: int = 100
    __volume_step: int = 5

    __vlc_instance: vlc.Instance = vlc.Instance("--aout=alsa")

    def __init__(self):
        self.__vlc_instance.log_unset() # disable VLC console output
        self.power = False
        self.volume = self.__default_volume
        self.channels = radiofrancechannels.get_radiofrance_channels()
        self.channel_num = 0
        self.media_player = self.__vlc_instance.media_player_new()
        self.current_channel = None
        self.display_text = None
        self.media = None
        self.set_display("OFF")

    def toggle_on_off(self):
        if not self.power:
            self.power = True
            self.current_channel = self.channels[self.channel_num]
            self.media = self.__vlc_instance.media_new(self.current_channel.get_channel_url())
            self.media.get_mrl()
            self.media_player.audio_set_volume(self.volume)
            self.media_player.set_media(self.media)
            self.current_channel.fetch_metadata(True)  # instead of media.parse() / Forcing update
            self.play()
        else:
            self.power = False
            self.stop()
        return self.power

    def play(self):
        self.media_player.play()

    def switch_channel(self, num: int) -> str:
        num =  (self.channel_num + num) % len(self.channels)
        if self.power:
            self.stop()
            self.channel_num = num
            self.current_channel = self.channels[self.channel_num]
            self.media = self.__vlc_instance.media_new(self.current_channel.get_channel_url())
            self.media.get_mrl()
            self.media_player.set_media(self.media)
            self.current_channel.fetch_metadata(True)  # instead of media.parse() / Forcing update
            self.play()
            return self.current_channel.get_channel_name()
        else:
            return ""

    def next_channel(self) -> str:
        return self.switch_channel(+1)

    def previous_channel(self) -> str :
        return self.switch_channel(-1)

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
            return "OFF"
        if self.media_player.get_state() == vlc.State.Ended or self.media_player.get_state() == vlc.State.Error:
            return f"{self.display_text} - /!\\ Error playing stream"
        else:
            return self.current_channel.get_display_text()

    def get_channel_name(self) -> str:
        if self.current_channel:
            return self.current_channel.get_channel_name()
        return ""

    def get_debug(self):
        if self.current_channel:
            return self.current_channel.get_debug()
        return ""