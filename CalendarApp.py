from __future__ import print_function
import os.path
import datetime
import re
import bs4
import Event
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests
from requests import adapters
import ssl
from urllib3 import poolmanager

DEFAULT_SCOPES = ['https://www.googleapis.com/auth/calendar']
DEFAULT_CALENDAR_ID = 'b5d70ec1afdce64dc795396461dafe97bb82e3ab3f0f6933e3404830d9660714@group.calendar.google.com'
DEFAULT_URLS = {'two_weeks': "https://planzajec.uek.krakow.pl/index.php?typ=G&id=186581&okres=1",
                'semester': "https://planzajec.uek.krakow.pl/index.php?typ=G&id=186581&okres=2"}
DEFAULT_TIME_OFFSET = datetime.timedelta(days=14)


class CalendarApp:
    def __init__(self, calendar_id=DEFAULT_CALENDAR_ID, time_offset=DEFAULT_TIME_OFFSET):
        self.scopes = DEFAULT_SCOPES
        self.calendar_id = calendar_id
        self.time_offset = time_offset

        self.creds = self._get_credentials()
        self.service = self._get_service()

    def update_upcoming_two_weeks(self):
        now = datetime.datetime.today()
        now = now.replace(hour=0, minute=0, second=0, microsecond=0)
        now_plus_two_weeks = now + datetime.timedelta(days=14)
        now = now.isoformat() + 'Z'
        now_plus_two_weeks = now_plus_two_weeks.isoformat() + 'Z'
        self._delete_events(now, now_plus_two_weeks)
        events_to_add = self._get_plan(DEFAULT_URLS['two_weeks'])
        self._insert_events(events_to_add)

    def _get_credentials(self):
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', self.scopes)
            # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', self.scopes)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return creds

    def _get_service(self):
        try:
            service = build('calendar', 'v3', credentials=self.creds)
            return service
        except HttpError as error:
            print(f'Connection error occurred: {error}')
            raise

    def _insert_events(self, events=()):
        for event in events:
            self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
            print(f"Event created: {event.get('summary')}")

    def _get_plan(self, plan_url):
        class TLSAdapter(adapters.HTTPAdapter):
            def init_poolmanager(self, connections, maxsize, block=False):
                """Create and initialize the urllib3 PoolManager."""
                ctx = ssl.create_default_context()
                ctx.set_ciphers('DEFAULT@SECLEVEL=1')
                self.poolmanager = poolmanager.PoolManager(
                    num_pools=connections,
                    maxsize=maxsize,
                    block=block,
                    ssl_version=ssl.PROTOCOL_TLS,
                    ssl_context=ctx)

        session = requests.session()
        session.mount('https://', TLSAdapter())
        try:
            r = session.get(plan_url, proxies={"http": "http://lab-proxy.krk-lab.nsn-rdnet.net:8080",
                                          "https": "http://lab-proxy.krk-lab.nsn-rdnet.net:8080"})
        except Exception as e:
            print(f"Encountered exception: {e}\n"
                  f"Trying to request resource without proxy...")
            r = session.get(plan_url)

        soup = bs4.BeautifulSoup(r.content, 'html.parser')
        table = soup.find('table')

        headers = [header.text for header in table.find_all('th')]
        results = [{headers[i]: cell for i, cell in enumerate(row.find_all('td'))}
                   for row in table.find_all('tr')]

        events = []
        for event in results[1:]:  # Skip first event
            start, end = re.findall(r"\d\d:\d\d", event['Dzień, godzina'].text)
            start_formatted = datetime.datetime.strptime(f"{event['Termin'].text} {start}", "%Y-%m-%d %H:%M")
            end_formatted = datetime.datetime.strptime(f"{event['Termin'].text} {end}", "%Y-%m-%d %H:%M")
            event_type = event['Typ'].text
            if "ćwiczenia" in event_type:
                event_type_short = "Ćw"
            elif "wykład" in event_type:
                event_type_short = "Wk"
            elif "lektorat" in event_type:
                event_type_short = "Lk"
            else:
                event_type_short = ""
            summary = f"{event_type_short}{' ' if event_type_short else ''}{event['Przedmiot'].text}"
            link = ""
            if isinstance(link_container := event['Sala'].contents[0], bs4.element.Tag):
                link = link_container.attrs['href']
            description = f"Prowadzący: {event['Nauczyciel'].text}\n" \
                          f"{event['Sala'].text.title()}{': ' + link if link else ''}"
            events.append(Event.Event(start_formatted, end_formatted, summary, description).get_calendar_event())
        return events

    def _delete_events(self, time_min, time_max):
        print(f'Getting events for deletion between {time_min} and {time_max}')
        events_result = self.service.events().list(calendarId=self.calendar_id,
                                                   singleEvents=True, timeMin=time_min,
                                                   timeMax=time_max, orderBy='startTime').execute()
        events = events_result.get('items', [])

        if not events:
            print('No events found.')
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            event_id = event['id']
            print(f"Deleting: {start} {event['summary']}...")
            self.service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()


if __name__ == '__main__':
    app = CalendarApp()
    app.update_upcoming_two_weeks()
