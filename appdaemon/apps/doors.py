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
CONF_NOTIFY_THRESHOLD = "notify_threshold"

TIMER_ENTITY = 'entities_timer'
TIMER_NOTIFY = 'notify_timer'
TIMER_INTRUDER = 'intruder_timer'
TIMER_SUPPRESS = 'suppress_timer'
LISTENER_INTRUDER = 'intruder_listener'

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
    vol.Optional(CONF_NOTIFY_THRESHOLD, default=3): vol.All(int, vol.Range(min=2)),
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
        self.notify_threshold = args.get(CONF_NOTIFY_THRESHOLD)

        self._override_sundown = False
        self._entity_lock = False
        self._suppress_next_hit = False

        self.handles = {}
        self.entity_handles = {}
        self.zwave = {}
        self._opencount = 0

        self.log(self.name, level=INFO)

        # load people tracker.
        self.peopletracker = self.get_app('peopletracker')
        self.utils = self.get_app('utils')
        if self.utils:
            self._countstart = self.utils.create_timer()
            self.door_users = USERS_OF_DOOR_ENTITY_ID.format(self.utils.get_object_id(self.sensor))
        
            self.listen_state(self.track_door, entity = self.sensor)
            
            # This is a band aid.  It appears that home assistant or appdaemon suppresses on->on for zwave devices.
            # So, to recify this, I'm going to search for the matching zwave domain entity.  Then, use that to track calls.
            # when a call is made, take a snapshot of the state.  Really stupid that this is required.

            zwave = self.get_state('zwave')
            if self.entities and zwave:
                for entity in self.entities:
                
                    state = self.utils.get_snapshot(self.name, entity)
                
                    node_id = self.get_state(entity, attribute='node_id')
                    filtered = [ k for k, v in zwave.items() if v['attributes']['node_id'] == node_id ]
                    try:
                        self.zwave[entity] = filtered[0]
                        self.log("Paired {} with {}".format(self.zwave[entity], entity), level=DEBUG)
                    except IndexError:
                        self.log("Did not find a zwave entity for {}".format(entity), level=DEBUG)
        else:
            raise NameError("name 'utils' is not defined")
        
    def cancel_door_handle(self, name):
        if name in self.handles:
            id = "{}.handles['{}']".format(self.name, name)
            self.log("Destroying %s."%id, level = DEBUG)
            self.cancel_timer(self.handles[name])
        
    def create_door_timer(self, method, name, duration, **kwargs):
        kwargs[SECONDS] = duration
        id = "{}.handles['{}']".format(self.name, name)
        self.log("Creating %s."%id, level = DEBUG)
        self.handles[name] = self.run_in(method, duration, **kwargs)

    def cancel_entity_listener(self, entity):
        if entity in self.entity_handles:
            id = "{}.entity_handles['{}']".format(self.name, entity)
            self.log("Destroying %s."%id, level = DEBUG)
            self.cancel_listen_state(self.entity_handles[entity])

    def start_entities_timer(self, **kwargs):
        # Cancel timers for restoring states of entities
        self.cancel_door_handle(TIMER_ENTITY)
        if self.sun_down() or self._override_sundown:
            # start a timer to restore the state prior to the door being opened.
            self.create_door_timer(self.restore_states, TIMER_ENTITY, self.on_duration, **kwargs)

    def turn_on_entities(self):
        """ turns on entities """
        self._entity_lock = True
        if self.sun_down() or self._override_sundown:
            for entity in self.entities:
                if not self.utils.have_snapshot(self.name, entity):
                    state = self.utils.take_snapshot(self.name, entity)
                    self.log("Storing state: {} for {}".format(state, entity), level=DEBUG)
                    self._suppress_next_hit = True

                self.turn_on_entity(entity)
                id = "{}.entity_handles['{}']".format(self.name, entity)
                self.log("Creating %s."%id, level = DEBUG)
                
                self.cancel_entity_listener(entity)
                
                if entity in self.zwave:
                    #self.entity_handles[entity] = self.listen_state(self.track_override, entity = self.zwave[entity], attribute='receivedCnt', tracking = entity)
                    self.entity_handles[entity] = self.listen_state(self.track_override, entity = self.zwave[entity], attribute='sentCnt', tracking = entity)
                else:
                    self.entity_handles[entity] = self.listen_state(self.track_override, entity = entity, tracking = entity)
        self._entity_lock = False

    def track_override(self, entity, attribute, old, new, kwargs):
        # This has a bandaid in it.  We should be able to track off new, but we can't.
        # So, we have to pass the entity_id inside 'tracking'.
        # then we need to store that state.
        entity_id = kwargs.get('tracking')
        if entity_id and not self._entity_lock and not self._suppress_next_hit:
            time.sleep(0.5) # another band aid to make this work.
            state = self.utils.take_snapshot(self.name, entity_id)
            self.log("Override state: {} for {}".format(state, entity_id), level=DEBUG)
        self._suppress_next_hit = False
        
    def track_door(self, entity, attribute, old, new, kwargs):
        
        # kwargs to use for timers.  Just replace seconds.
        tkwargs = {SECONDS: 0, ENTITY: entity, STATE: new }
        
        self.log('track_door.callback', level=DEBUG)
        
        if self._opencount == 0:
            self._countstart.reset()

        # Cancel notification timers for door being open too long.
        self.cancel_door_handle(TIMER_NOTIFY)

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
                self.cancel_door_handle(TIMER_SUPPRESS)
                # start the timer for suppression of annoucements.
                self.create_door_timer(self.reset_counter ,TIMER_SUPPRESS, self.suppress_duration, **tkwargs)

                if self.peopletracker:
                    message = self.peopletracker.people_used_sensor(self.door_name)

                    self.write_users_of_door_to_entity()

                    if len(self.peopletracker.people_at_home) == 0:
                        self.cancel_door_handle(LISTENER_INTRUDER)
                    
                        self.handles[LISTENER_INTRUDER] = self.listen_state(self.track_intruder, entity = self.peopletracker.count_entity_id)

                        # Cancel notification timer for the intruder and start a new one.
                        self.cancel_door_handle(TIMER_INTRUDER)

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
        id = "{}.handles['{}']".format(self.name, LISTENER_INTRUDER)
        self.log("Destroying {}.".format(id), level = DEBUG)
        self.cancel_listen_state(self.handles[LISTENER_INTRUDER])

    def track_intruder(self, entity, attribute, old, new, kwargs):
        if int(new) > 0:
            people = self.peopletracker.people_conjunction('or')
            
            who = 'people' if int(new) > 1 else 'person'
            message = 'The {} who used the door was {}.'.format(who, people)
            self.utils.send_notifications(self.notify, message)
            # Try to cancle the state listener.
            self.cancel_intruder_listener()
            self.cancel_door_handle(TIMER_INTRUDER)

    def turn_on_entity(self, entity):
        if self.utils.is_domain(entity, LIGHT):
            attributes_off = any([ self.get_state(entity, attribute=attr) != value for attr, value in LIGHT_ATTRIBUTES.items() ])
            off = self.get_state(entity) == STATE_OFF
            if off or attributes_off:
                self.turn_on(entity, **LIGHT_ATTRIBUTES)
        else:
            if self.get_state(entity) == STATE_OFF:
                self.turn_on(entity)
            
    def reset_counter(self, kwargs):
        if self._opencount >= self.notify_threshold:
            duration = self._countstart.elapsed_conversation(False)
            message = "The {} was opened {} times over the past {}".format(self.door_name, self._opencount, duration)
            self.utils.send_notifications(self.notify, message)
        self._opencount = 0

    def restore_states(self, kwargs):
        entity = kwargs.get(ENTITY)

        for entity in self.entities:

            # get the snapshot of the state before turning on the lights.
            state = self.utils.get_snapshot(self.name, entity)
            if state:
                self.log("Recalling state: {} for {}".format(state.state, state.entity_id), level=DEBUG)

                if self.get_state(state.entity_id) != state.state:
                    if state.state == STATE_ON:
                        self.turn_on_entity(entity)
                    elif state.state == STATE_OFF:
                        self.turn_off(entity)
            
            if entity in self.entity_handles:
                id = "{}.entity_handles['{}']".format(self.name, entity)
                self.log("Canceling %s."%id, level = DEBUG)
                self.cancel_listen_state(self.entity_handles[entity])

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