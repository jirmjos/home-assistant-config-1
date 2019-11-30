import appdaemon.plugins.hass.hassapi as hass
import voluptuous as vol

CONF_MODULE = 'module'
CONF_CLASS = 'class'
CONF_EVENTS = 'events'

INFO = 'INFO'

APP_SCHEMA = vol.Schema({
    vol.Required(CONF_MODULE): str,
    vol.Required(CONF_CLASS): str,
    vol.Required(CONF_EVENTS): [str],
})

class EventMonitor(hass.Hass):
    def initialize(self):
        #args = APP_SCHEMA(self.args)

        self.events = events = self.args.get(CONF_EVENTS)

        self.handles = []
        
        if events:
            for event in events:
                self.log("Watching event '{}'".format(event), level=INFO)
                self.handles.append(
                    self.listen_event(self.monitor_event, event)
                )
            
        else:
            self.log("Watching all events", level=INFO)
            self.handles.append(self.listen_event(self.monitor_event))
        
    def monitor_event(self, event_name, data, kwargs):
        msg = '{}: {}'.format(event_name, str(data))
        self.log(msg, level='INFO')

    def terminate(self):
        for handle in self.handles:
            self.log('Canceling handle {}'.format(self.handles.index(handle)+1), level=INFO)
            self.cancel_listen_event(handle)