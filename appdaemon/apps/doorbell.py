import appdaemon.plugins.hass.hassapi as hass
import voluptuous as vol

CONF_MODULE = 'module'
CONF_CLASS = 'class'
CONF_DOOR_BELL = 'door_bell'
CONF_NOTIFY = "notify"
CONF_DEBUG = "debug"
CONF_MEDIA_PLAYER = "media_player"
INFO = 'INFO'

APP_SCHEMA = vol.Schema({
    vol.Required(CONF_MODULE): str,
    vol.Required(CONF_CLASS): str,
    vol.Required(CONF_DOOR_BELL): str,
    vol.Optional(CONF_NOTIFY, default=[]): [str],
    vol.Optional(CONF_MEDIA_PLAYER, default=[]): [str],
    vol.Optional(CONF_DEBUG, default=False): bool,
})

class DoorBell(hass.Hass):
    def initialize(self):
        args = APP_SCHEMA(self.args)

        self.door_bell = args.get(CONF_DOOR_BELL)
        self.notify = args.get(CONF_NOTIFY)
        self.media_player = args.get(CONF_MEDIA_PLAYER)
        self._level = 'INFO' if args.get(CONF_DEBUG) else 'DEBUG'
        self.log(args, level=self._level)
        
        self.handles = []

        self.utils = self.get_app('utils')
        if self.utils:
            if self.notify or self.media_player:
                self.log("Listening '{}'".format(self.door_bell), level=self._level)
                self.handles.append(
                    self.listen_state(self.monitor_event, entity = self.door_bell, new='on')
                    )
        else:
            raise NameError("name 'utils' is not defined")
        
    def monitor_event(self, entity, attribute, old, new, kwargs):
        if self.notify:
            self.log("Sending notification", level = self._level)
            self.utils.send_notifications(self.notify, 'DoorBell')
        
        if self.media_player:
            self.log("Announcing to alexa", level = self._level)
            data = {"message": "Someone is at the door", "data":{"type":"tts"}, "target": self.media_player}
            self.call_service('notify/alexa_media', **data)

    def terminate(self):
        for handle in self.handles:
            self.log('Canceling handle {}'.format(self.handles.index(handle)+1), level=self._level)
            self.cancel_listen_event(handle)