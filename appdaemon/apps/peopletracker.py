import appdaemon.plugins.hass.hassapi as hass
import voluptuous as vol

CONF_MODULE = 'module'
CONF_CLASS = 'class'
CONF_ENTITIES = 'entities'
CONF_COMPANY = 'company'

PEOPLE_TRACKED_ENTITY_ID = 'sensor.people_tracked'

APP_SCHEMA = vol.Schema({
    vol.Required(CONF_MODULE): str,
    vol.Required(CONF_CLASS): str,
    vol.Required(CONF_ENTITIES): [ str ],
    vol.Optional(CONF_COMPANY): str})

class PeopleTracker(hass.Hass):
    def initialize(self):
        args = APP_SCHEMA(self.args)
        self.log(args, level = 'INFO')

        self.entities = args.get(CONF_ENTITIES, [])
        self.guest_entity_id = args.get(CONF_COMPANY)

        self.count_entity_id = PEOPLE_TRACKED_ENTITY_ID

        self.log(self.get_state(self.guest_entity_id, attribute='all'), level = 'INFO')

        self._people = []

        for entity_id in self.entities:
            self.listen_state(self.track_person, entity = entity_id)

        if self.guest_entity_id:
            self.listen_state(self.track_guests, entity = self.guest_entity_id)

        #Populate people on startup.
        self.find_people()

        self.log(self.people_conjunction(), level='INFO')

        self._set_people_state()

    def clean_persons_name(self, entity_id):
        """ 
        clean the name, de-plualize it in case this is a phone and we 
          don't have a person.
        """
        name = self.friendly_name(entity_id)
        name = name.lower().replace(' iphone','').strip()
        if name.endswith("'s"):
            name = name[:-2]
        return name.title()

    def track_person(self, entity, attribute, old, new, kwargs):
        name = self.clean_persons_name(entity)
        if new in ['home']:
            self.add_person(name)
        else:
            self.remove_person(name)

    def add_person(self, name):
        # I forget why this was added but it was added for a reason.
        # Most likely because I have more than 1 device tracker per person
        # and this was created before Person existed.  Leave it for now.
        if name not in self._people and name[:-1] not in self._people:
            before = str(self._people)
            self._people.append(name)
            self._people.sort()
            after = str(self._people)
            self.log('%s -> %s'%(before, after), level='DEBUG')
            self._set_people_state()

    def remove_person(self, name):
        if name in self._people:
            before = str(self._people)
            idx = self._people.index(name)
            self._people.pop(idx)
            after = str(self._people)
            self.log('%s -> %s'%(before, after), level='DEBUG')
            self._set_people_state()

    def track_guests(self, entity, attribute, old, new, kwargs):
        guests = 'Guests'
        if new in ['on','enabled','home']:
            self.add_person(guests)
        else:
            self.remove_person(guests)

    def find_people(self):
        for entity_id in self.entities:
            if self.get_state(entity_id) in [ 'home' ]:
                name = self.clean_persons_name(entity_id)
                self.add_person(name)
        if self.guest_entity_id:
            if self.get_state(self.guest_entity_id) in ['on','enabled','home']:
                self.add_person('Guests')

    @property
    def people_at_home(self): return self._people

    def people_conjunction(self, conjunction='and'):
        people = self.people_at_home
        if len(people) == 0:
            return "Unknown"
        elif len(people) == 1:
            return people[0]
        elif len(people) == 2:
            return ' {} '.format(conjunction).join(people)
        else:
            return "{}, {} {}".format(', '.join(people[:-1]), conjunction, people[-1])

    def people_used_sensor(self, sensor_name):
        if not self.people_at_home:
            return "Unknown person used the {}.".format(sensor_name)
        else:
            people = self.people_conjunction('or')
            return '{} used the {}.'.format(people, sensor_name)
            
    def _set_people_state(self):
        state = str(len(self._people))
        self.set_state(self.count_entity_id, state=state)