import appdaemon.plugins.hass.hassapi as hass
import voluptuous as vol
import time

CONF_MODULE = 'module'
CONF_CLASS = 'class'
CONF_SENSOR = "sensor_id"
CONF_NAME = "sensor_name"
CONF_TURN_ON = "turn_on"
CONF_TURN_ON_FOR = "turn_on_for"
CONF_NOTIFY = "notify"
CONF_DOOR_OPEN = "door_open_for"
CONF_SUPPRESS = "suppress_duplicate_window"
CONF_INTRUDER = "intruder_timeout"

TIMER_ENTITY = 'entities'
TIMER_NOTIFY = 'notify'
TIMER_INTRUDER = 'intruder'
TIMER_SUPPRESS = 'suppress'

SECONDS = 'timer_seconds'
ENTITY = 'timer_entity'
STATE = 'timer_state'

INFO = 'INFO'
DEBUG = INFO
#DEBUG = 'DEBUG'

STATE_ON = 'on'
STATE_OFF = 'off'

DOOR_CLOSED = [ STATE_OFF, 'closed', '23' ]
DOOR_OPEN = [ STATE_ON, 'open', '22']

LIGHT_ATTRIBUTES = {'brightness':255}

USERS_OF_DOOR_ENTITY_ID = 'sensor.{}_message'

LIGHT = 'light'

APP_SCHEMA = vol.Schema({
    vol.Required(CONF_MODULE): str,
    vol.Required(CONF_CLASS): str,
    vol.Required(CONF_SENSOR): str,
    vol.Optional(CONF_NAME): str,
    vol.Optional(CONF_TURN_ON): [str],
    vol.Optional(CONF_TURN_ON_FOR, default=120): vol.All(int, vol.Range(min=1)),
    vol.Optional(CONF_NOTIFY): [str],
    vol.Optional(CONF_DOOR_OPEN, default=15): vol.All(int, vol.Range(min=1)),
    vol.Optional(CONF_SUPPRESS, default=180): vol.All(int, vol.Range(min=1)),
    vol.Optional(CONF_INTRUDER, default=60): vol.All(int, vol.Range(min=1)),
})

class DoorHandler(hass.Hass):
    def initialize(self):
        args = APP_SCHEMA(self.args)
        self.log(args, level=DEBUG)
        
        self.sensor = args.get(CONF_SENSOR)
        self.door_name = args.get(CONF_NAME, self.friendly_name(self.sensor)).capitalize()
        self.entities = args.get(CONF_TURN_ON, [])
        self.on_duration = args.get(CONF_TURN_ON_FOR)
        self.notify = args.get(CONF_NOTIFY, [])
        self.door_duration = args.get(CONF_DOOR_OPEN)
        self.suppress_duration = args.get(CONF_SUPPRESS)
        self.intruder_timeout = args.get(CONF_INTRUDER)

        self._override_sundown = False

        self.timers = {}
        self.intruder = None
        self._opencount = 0

        self.log(self.name, level=INFO)

        # load people tracker.
        self.peopletracker = self.get_app('peopletracker')
        self.utils = self.get_app('utils')
        if self.utils:
            self._countstart = self.utils.create_timer()
            self.door_users = USERS_OF_DOOR_ENTITY_ID.format(self.utils.get_object_id(self.sensor))
        
            self.listen_state(self.track_door, entity = self.sensor)
        else:
            raise NameError("name 'utils' is not defined")
        
    def cancel_door_timer(self, name):
        if name in self.timers:
            id = "{}.timers['{}']".format(self.name, name)
            self.log("Canceling %s timer."%id, level = DEBUG)
            self.cancel_timer(self.timers[name])
        
    def create_door_timer(self, method, name, duration, **kwargs):
        kwargs[SECONDS] = duration
        id = "{}.timers['{}']".format(self.name, name)
        self.log("Creating %s timer."%id, level = DEBUG)
        self.timers[name] = self.run_in(method, duration, **kwargs)
        
    def start_entities_timer(self, **kwargs):
        # Cancel timers for restoring states of entities
        self.cancel_door_timer(TIMER_ENTITY)
        if self.sun_down() or self._override_sundown:
            # start a timer to restore the state prior to the door being opened.
            self.create_door_timer(self.restore_states, TIMER_ENTITY, self.on_duration, **kwargs)
        
    def turn_on_entities(self):
        """ turns on entities """
        if self.sun_down() or self._override_sundown:
            for entity in self.entities:
                if not self.utils.have_snapshot(entity):
                    state = self.utils.take_snapshot(entity)
                    self.log("Storing state: {} for {}".format(state, entity), level=DEBUG)

                self.turn_on_entity(entity)

    def track_door(self, entity, attribute, old, new, kwargs):
        
        # kwargs to use for timers.  Just replace seconds.
        tkwargs = {SECONDS: 0, ENTITY: entity, STATE: new }
        
        self.log('track_door.callback', level=DEBUG)
        
        if self._opencount == 0:
            self._countstart.reset()

        # Cancel notification timers for door being open too long.
        self.cancel_door_timer(TIMER_NOTIFY)

        if new in DOOR_CLOSED:
            # start the timer for resuming state on entities.
            if self.entities:
                self.start_entities_timer(**tkwargs)

        if new in DOOR_OPEN:

            self._opencount += 1

            if self.entities:
                # turn on all the entities
                self.turn_on_entities()

            if self.notify:
                # start the timer for notifying if the door is open for x seconds.
                self.create_door_timer(self.notify_door_open, TIMER_NOTIFY, self.door_duration, **tkwargs)

                # Cancel suppression timers for door annoucements.
                self.cancel_door_timer(TIMER_SUPPRESS)
                # start the timer for suppression of annoucements.
                self.create_door_timer(self.reset_counter ,TIMER_SUPPRESS, self.suppress_duration, **tkwargs)

                if self.peopletracker:
                    message = self.peopletracker.people_used_sensor(self.door_name)

                    self.write_users_of_door_to_entity()

                    if len(self.peopletracker.people_at_home) == 0:
                        self.intruder = self.listen_state(self.track_intruder, entity = self.peopletracker.count_entity_id)

                        # Cancel notification timer for the intruder and start a new one.
                        self.cancel_door_timer(TIMER_INTRUDER)

                        # start an intruder timer to announce that we never found anyone.
                        self.create_door_timer(self.intruder_notify, TIMER_INTRUDER, self.intruder_timeout, **tkwargs)
                else:
                    message = "{} is open.".format(self.door_name)

                if self._opencount <= 1:
                    self.utils.send_notifications(self.notify, message)

    def intruder_notify(self, kwargs):
        message = 'The person who used {} is still unknown!'.format(self.door_name)
        self.utils.send_notifications(self.notify, message)
        self.cancel_intruder_listener()

    def cancel_intruder_listener(self):
        self.log("Canceling intruder listener", level = DEBUG)
        self.cancel_listen_state(self.intruder)

    def track_intruder(self, entity, attribute, old, new, kwargs):
        if int(new) > 0:
            people = self.peopletracker.people_conjunction('or')
            
            who = 'people' if int(new) > 1 else 'person'
            message = 'The {} who used the door was {}.'.format(who, people)
            self.utils.send_notifications(self.notify, message)
            # Try to cancle the state listener.
            self.cancel_intruder_listener()
            self.cancel_door_timer(TIMER_INTRUDER)

    def turn_on_entity(self, entity):
        if self.utils.is_domain(entity, LIGHT):
            self.turn_on(entity, **LIGHT_ATTRIBUTES)
        else:
            self.turn_on(entity)
            
    def reset_counter(self, kwargs):
        if self._opencount > 1:
            duration = self._countstart.elapsed_conversation(False)
            message = "The {} was opened {} times over the past {}".format(self.door_name, self._opencount, duration)
            self.utils.send_notifications(self.notify, message)
        self._opencount = 0

    def restore_states(self, kwargs):
        entity = kwargs.get(ENTITY)

        for entity in self.entities:

            # get the snapshot of the state before turning on the lights.
            state = self.utils.get_snapshot(entity)
            if state:
                self.log("Recalling state: {} for {}".format(state.state, state.entity_id), level=DEBUG)

                if self.get_state(state.entity_id) != state.state:
                    if state.state == STATE_ON:
                        self.turn_on_entity(entity)
                    elif state.state == STATE_OFF:
                        self.turn_off(entity)
                        
    def notify_door_open(self, kwargs):
        state = kwargs.get(STATE)
        seconds = kwargs.get(SECONDS)
        message = '{} has been {} for more than {} seconds.'.format(
            self.door_name, state, seconds)
        self.utils.send_notifications(self.notify, message)
        
    def write_users_of_door_to_entity(self):
        if self.peopletracker:
            state = self.peopletracker.people_conjunction()
            self.utils.write(self.door_users, state)
            self.set_state(self.door_users, state=state)