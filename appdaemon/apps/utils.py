import appdaemon.plugins.hass.hassapi as hass
import json
import shelve
import time
from datetime import timedelta, datetime

STATE_RESTORE = "/config/appdaemon/states"
INFO = 'INFO'
DEBUG = 'INFO'
#DEBUG = 'DEBUG'

class OnDiskDatabase(object):
    def __init__(self, filename):
        """ class for storing and restoring states on disk."""
        self._filename = filename

    def write(self, entity_id, state):
        with shelve.open(self._filename) as db:
            db[entity_id] = json.dumps({'state':state})

    def read(self, entity_id):
        with shelve.open(self._filename) as db:
            if entity_id in db.keys():
                state_dict = json.loads(db[entity_id])
                return state_dict['state']
            else:
                return ""

class StateSnapShot(object):
    def __init__(self, entity_id, state="", **kwargs):
        self._entity_id = entity_id
        self._state = state
        self._attributes = kwargs.get('attributes', {})
        self.restore = True
        
    @property
    def entity_id(self):
        return self._entity_id
        
    @property
    def state(self):
        return self._state
        
    @property
    def attributes(self):
        return self._attributes
        
    def __repr__(self):
        return self._entity_id

class Timer(object):
    def __init__(self):
        self._start = time.time()

    def reset(self):
        self._start = time.time()

    @property
    def elapsed(self):
        return time.time() - self._start

    def elapsed_conversation(self, include_seconds=True):
        def plural(v, string):
            if v > 1:
                return '{} {}s'.format(v, string)
            else:
                return string

        hours, remainder = divmod(self.elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)

        if not include_seconds:
            minutes += int(round(seconds/60))

        hours, minutes, seconds = [ int(v) for v in [ hours, minutes, seconds ] ]

        ret = []
        if hours:
            ret.append(plural(hours, 'hour'))
        if minutes:
            ret.append(plural(minutes, 'minute'))
        if seconds and include_seconds:
            ret.append(plural(seconds, 'second'))

        if len(ret) == 0:
            return None
        elif len(ret) == 1:
            return ret[0]
        else:
            return ' and '.join(ret)

class StateSnapShotManager(object):
    def __init__(self):
        self._database = {}

    def set(self, entity_id, state, **kwargs):
        self._database[entity_id] = StateSnapShot(entity_id, state, **kwargs)

    def pop(self, entity_id):
        if entity_id in self._database:
            return self._database.pop(entity_id)
        return None
        
    def get(self, entity_id):
        return self._database.get(entity_id)

    def __getitem__(self, entity_id):
        if name in self._database:
            return self._database[name]
        else:
            raise KeyError("'{}'".format(entity_id))

class utils(hass.Hass):
    def initialize(self):
        self._disk = OnDiskDatabase(STATE_RESTORE)
        self._snapshots = StateSnapShotManager()
        self._timers = {}

    def read(self, entity_id):
        return self._disk.read(entity_id)

    def write(self, entity_id, state):
        self._disk.write(entity_id, state)

    def take_snapshot(self, entity_id):
        kwargs = self.get_state(entity_id, attribute='all')
        state = kwargs.pop('state')
        self._snapshots.set(entity_id, state, attributes=kwargs)
        return state

    def have_snapshot(self, entity_id):
        return self._snapshots.get(entity_id) is not None

    def get_snapshot(self, entity_id):
        return self._snapshots.pop(entity_id)
        
    def is_domain(self, entity_id, domain):
        return self.get_domain(entity_id) == domain

    def timestamp(self, message):
        dt = datetime.now()
        return "[{}] {}".format(dt.strftime('%-I:%M:%S %p'), message)
        
    def as_service_call(self, entity_id):
        # This should enforce a single period while also, providing an error if we
        # have more than one.  Might be overkill.
        return r'{}/{}'.format(*entity_id.split('.'))
        
    def get_object_id(self, entity_id):
        return entity_id.split('.')[-1]
        
    def get_domain(self, entity_id):
        return entity_id.split('.')[0]

    def send_notifications(self, entities, message, data={'push':{'badge': 1}}):
        msg = self.timestamp(message)
        self.log("{} <- {}".format(', '.join(entities), message), level = DEBUG)
        for entity in entities:
            service = self.as_service_call(entity)
            self.call_service(service, message=msg, data=data)

    def _try_cancel_method(self, method, name, handle):
        try:
            method(handle)
        except:
            self.log('Tried to {}({}), but none existed!'.format(method.__name__, name), level=DEBUG)

    def try_cancel_timer(self, name, handle):
        self._try_cancel_method(self.cancel_timer, name, handle)

    def try_cancel_listen_state(self, name, handle):
        self._try_cancel_method(self.cancel_listen_state, name, handle)

    def create_timer(self):
        return Timer()