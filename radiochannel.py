from abc import ABC, abstractmethod, abstractproperty


class RadioChannel(ABC):

    @property
    @abstractmethod
    def channel_type(self):
        pass

    @abstractmethod
    def get_channel_name(self) -> str:
        pass

    @abstractmethod
    def get_channel_url(self) -> str:
        pass

    @abstractmethod
    def get_current_track_info(self) -> dict[str, str]:
        pass

    @abstractmethod
    def get_display_text(self) -> str:
        pass

    @abstractmethod
    def fetch_metadata(self, force: bool = False):
        pass

    @abstractmethod
    def get_debug(self) -> str:
        pass